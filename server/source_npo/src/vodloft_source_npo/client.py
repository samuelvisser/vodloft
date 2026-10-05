"""Small NPO Start client with account cookies kept inside the Source process."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener

NPO_ORIGIN = "https://npo.nl"
START_API = f"{NPO_ORIGIN}/start/api"
PLAYER_API = "https://prod.npoplayer.nl"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/153.0 Safari/537.36 VodLoft/1"
)
_API_HOSTS = {"npo.nl", "www.npo.nl", "id.npo.nl", "prod.npoplayer.nl"}
_MAX_JSON = 4 * 1024 * 1024
_MAX_HTML = 6 * 1024 * 1024


class NPOError(RuntimeError):
    pass


class ApiUnavailable(NPOError):
    """The private website API is missing, broken or returned an unknown shape."""


class AuthenticationRequired(NPOError):
    pass


class RateLimited(NPOError):
    pass


class MediaUnavailable(NPOError):
    pass


class DRMProtected(NPOError):
    pass


@dataclass(frozen=True)
class Playback:
    url: str
    transport: str
    headers: dict[str, str]


def _validate_npo_service_url(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or host not in _API_HOSTS or
            parsed.username is not None or parsed.password is not None):
        raise ValueError("NPO Source refused an unexpected network destination")
    return url


class _SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_npo_service_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _HiddenInputs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag != "input":
            return
        values = dict(attrs)
        name, value = values.get("name"), values.get("value")
        if name and value is not None:
            self.values[name] = value


class NPOClient:
    def __init__(self, email: str | None = None, password: str | None = None):
        if bool(email) != bool(password):
            raise ValueError("NPO account email and password must be supplied together")
        self.email = email.strip() if email else None
        self.password = password
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies), _SafeRedirects())
        self._authenticated = False

    @staticmethod
    def _validate_url(url: str, hosts: set[str] = _API_HOSTS) -> str:
        _validate_npo_service_url(url)
        if (urlsplit(url).hostname or "").lower() not in hosts:
            raise ValueError("NPO Source refused an unexpected network destination")
        return url

    def _request(self, url: str, *, data: bytes | None = None,
                 headers: dict[str, str] | None = None, limit: int = _MAX_JSON,
                 retry_auth: bool = False) -> tuple[str, bytes]:
        self._validate_url(url)
        request_headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": USER_AGENT,
            "Referer": f"{NPO_ORIGIN}/start",
            **(headers or {}),
        }
        request = Request(url, data=data, headers=request_headers)
        try:
            with self.opener.open(request, timeout=25) as response:
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise ApiUnavailable("NPO response exceeded the Source limit")
                return response.geturl(), body
        except HTTPError as exc:
            if exc.code in (401, 403):
                if retry_auth and self.email and not self._authenticated:
                    self.login()
                    return self._request(url, data=data, headers=headers, limit=limit,
                                         retry_auth=False)
                raise AuthenticationRequired("NPO account authentication is required") from exc
            if exc.code == 404:
                raise MediaUnavailable("NPO media was not found") from exc
            if exc.code == 429:
                raise RateLimited("NPO rate limit reached") from exc
            if exc.code >= 500:
                raise ApiUnavailable("NPO API is temporarily unavailable") from exc
            raise ApiUnavailable("NPO API rejected the request") from exc
        except (URLError, TimeoutError) as exc:
            raise ApiUnavailable("NPO API is temporarily unavailable") from exc

    @staticmethod
    def _decode_json(body: bytes):
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise ApiUnavailable("NPO returned an invalid JSON response") from exc

    def json(self, url: str, *, authenticated: bool = False):
        if authenticated:
            if not self.email:
                raise AuthenticationRequired("NPO account authentication is required")
            self.login()
        _, body = self._request(url, retry_auth=bool(self.email))
        return self._decode_json(body)

    def api(self, endpoint: str, **query):
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", endpoint):
            raise ValueError("Invalid NPO API endpoint")
        values = {key: str(value).lower() if isinstance(value, bool) else str(value)
                  for key, value in query.items() if value is not None}
        suffix = "?" + urlencode(values) if values else ""
        return self.json(f"{START_API}/domain/{endpoint}{suffix}")

    def html(self, url: str) -> str:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or host not in {"npo.nl", "www.npo.nl"}:
            raise ValueError("Only NPO web pages can be crawled")
        canonical = parsed._replace(scheme="https", netloc="npo.nl", fragment="").geturl()
        _, body = self._request(canonical, limit=_MAX_HTML, retry_auth=bool(self.email))
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ApiUnavailable("NPO web page was not UTF-8") from exc

    def _session(self) -> dict:
        _, body = self._request(f"{START_API}/auth/session", retry_auth=False)
        value = self._decode_json(body)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _session_valid(session: dict) -> bool:
        expires = session.get("tokenExpiresAt")
        return bool(session) and (
            not isinstance(expires, (int, float)) or float(expires) > time.time() + 30
        )

    def login(self) -> dict:
        if self._authenticated:
            session = self._session()
            if self._session_valid(session):
                return session
            self._authenticated = False
        if not self.email or not self.password:
            raise AuthenticationRequired("NPO account authentication is required")

        current = self._session()
        if self._session_valid(current):
            self._authenticated = True
            return current

        _, csrf_body = self._request(f"{START_API}/auth/csrf")
        csrf = self._decode_json(csrf_body)
        token = csrf.get("csrfToken") if isinstance(csrf, dict) else None
        if not isinstance(token, str) or not token:
            raise ApiUnavailable("NPO login did not return a CSRF token")

        sign_in = json.dumps({
            "callbackUrl": f"{START_API}/auth/session",
            "csrfToken": token,
            "json": True,
        }).encode()
        final_url, login_body = self._request(
            f"{START_API}/auth/signin/npo-id",
            data=sign_in,
            headers={"Content-Type": "application/json"},
            limit=_MAX_HTML,
        )

        # NextAuth deployments may either redirect to NPO ID directly or
        # return the login URL in a small JSON document.
        try:
            sign_in_result = self._decode_json(login_body)
        except ApiUnavailable:
            sign_in_result = None
        if isinstance(sign_in_result, dict) and isinstance(sign_in_result.get("url"), str):
            login_url = sign_in_result["url"]
            self._validate_url(login_url)
            final_url, login_body = self._request(login_url, limit=_MAX_HTML)

        if urlsplit(final_url).hostname in {"npo.nl", "www.npo.nl"}:
            try:
                session = self._decode_json(login_body)
            except ApiUnavailable:
                session = {}
            if isinstance(session, dict) and self._session_valid(session):
                self._authenticated = True
                return session

        try:
            login_html = login_body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ApiUnavailable("NPO login page was not UTF-8") from exc
        parser = _HiddenInputs()
        parser.feed(login_html)
        return_url = parser.values.get("ReturnUrl")
        verification = parser.values.get("__RequestVerificationToken")
        if not return_url or not verification:
            raise ApiUnavailable("NPO login form changed")

        form = urlencode({
            "EmailAddress": self.email,
            "Password": self.password,
            "ReturnUrl": return_url,
            "__RequestVerificationToken": verification,
            "button": "login",
        }).encode()
        _, result = self._request(
            "https://id.npo.nl/account/login",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            limit=_MAX_HTML,
        )
        text = result.decode("utf-8", errors="replace")
        if "validation-summary" in text:
            raise AuthenticationRequired("NPO rejected the account credentials")

        session = self._session()
        if not self._session_valid(session):
            raise AuthenticationRequired("NPO account authentication did not complete")
        self._authenticated = True
        return session

    def series_detail(self, slug: str):
        return self.api("series-detail", slug=slug, includePremiumContent=True)

    def series_seasons(self, slug: str, series_type: str | None = None):
        return self.api("series-seasons", slug=slug, type=series_type,
                        includePremiumContent=True)

    def programs_by_season(self, guid: str):
        return self.api("programs-by-season", guid=guid, sort="firstBroadcastDate",
                        includePremiumContent=True)

    def programs_by_series(self, guid: str, limit: int = 250):
        return self.api("programs-by-series", seriesGuid=guid, limit=limit,
                        sort="firstBroadcastDate", includePremiumContent=True)

    def program_detail(self, slug: str):
        return self.api("program-detail", slug=slug, ageRestriction="undefined",
                        includePremiumContent=True)

    def search(self, query: str, search_type: str):
        if self.email:
            self.login()
        return self.api("search-collection-items", searchType=search_type,
                        partyId=1, searchQuery=query,
                        subscriptionType="premium" if self.email else "anonymous",
                        includePremiumContent=True)

    def _player_token(self, product_id: str, *, authenticated: bool = False) -> str:
        if authenticated:
            self.login()
        data = self.json(
            f"{START_API}/domain/player-token?{urlencode({'productId': product_id})}",
            authenticated=False,
        )
        token = data.get("jwt") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise ApiUnavailable("NPO player token is missing")
        return token

    @staticmethod
    def _playback_error(data: dict) -> str:
        body = data.get("body")
        if isinstance(body, str):
            return body
        if isinstance(body, dict):
            return str(body.get("message") or body.get("error") or "")
        return str(data.get("message") or "")

    def playback(self, product_id: str, referrer_url: str) -> Playback:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{2,160}", product_id):
            raise ValueError("Invalid NPO product ID")
        if self.email:
            self.login()
        jwt = self._player_token(product_id, authenticated=False)
        payload = json.dumps({
            "profileName": "hls",
            "referrerUrl": referrer_url,
        }).encode()
        _, body = self._request(
            f"{PLAYER_API}/stream-link",
            data=payload,
            headers={
                "Authorization": jwt,
                "Content-Type": "application/json",
                "Origin": NPO_ORIGIN,
                "Referer": f"{NPO_ORIGIN}/",
            },
            retry_auth=False,
        )
        data = self._decode_json(body)
        if not isinstance(data, dict):
            raise ApiUnavailable("NPO player returned an invalid response")
        if data.get("status"):
            message = self._playback_error(data).casefold()
            if any(word in message for word in ("subscription", "abonnement", "premium", "login", "account")):
                raise AuthenticationRequired("NPO account with access to this media is required")
            raise MediaUnavailable("NPO player could not provide this media")

        stream = data.get("stream")
        if isinstance(stream, str):
            stream = {"streamURL": stream}
        if not isinstance(stream, dict):
            raise ApiUnavailable("NPO player response has no stream")
        if stream.get("drm"):
            raise DRMProtected("NPO returned DRM-protected playback")
        url = stream.get("streamURL") or stream.get("url")
        parsed = urlsplit(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme != "https" or not parsed.hostname:
            raise ApiUnavailable("NPO player returned an invalid stream URL")
        return Playback(
            url=url,
            transport="hls" if parsed.path.lower().endswith(".m3u8") else "http",
            headers={
                "User-Agent": USER_AGENT,
                "Origin": NPO_ORIGIN,
                "Referer": f"{NPO_ORIGIN}/",
            },
        )
