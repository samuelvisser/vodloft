"""The NPO Start website API, as the npo.nl player uses it without an account."""
from __future__ import annotations

import threading
import time
from typing import Any

import requests

from .. import pacing
from . import account

ORIGIN = "https://npo.nl"
API = f"{ORIGIN}/start/api/domain"
STREAM_LINK = "https://prod.npoplayer.nl/stream-link"
SESSION = f"{ORIGIN}/start/api/auth/session"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
_TIMEOUT_SECONDS = 25
# A short pause between requests, so indexing a long series does not look like a scraper.
_PAUSE_SECONDS = 0.3


class NpoError(RuntimeError):
    pass


class NpoNotFoundError(NpoError):
    pass


class NpoSubscriptionError(NpoError):
    pass


class NpoClient:
    def __init__(self):
        self._http = requests.Session()
        self._http.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json", "Referer": f"{ORIGIN}/start"})
        self._lock = threading.Lock()
        self._last_request = 0.0

    def _pace(self) -> None:
        with self._lock:
            pacing.pause(self._last_request + _PAUSE_SECONDS - time.monotonic())
            self._last_request = time.monotonic()

    def _send(self, method: str, url: str, *, cookies=None, **kwargs) -> Any:
        self._pace()
        try:
            response = self._http.request(method, url, timeout=_TIMEOUT_SECONDS, cookies=cookies, **kwargs)
        except requests.RequestException as exc:
            raise NpoError(f"NPO Start could not be reached: {exc}") from exc
        if cookies is not None:
            # npo.nl renews the sign-in on every signed-in answer and stops honouring
            # the old one, so the renewed cookies go back into the cookies file. The
            # catalogue stays anonymous, so the shared session keeps none of them.
            self._http.cookies.clear()
            if response.cookies:
                account.keep_cookies(cookies, response.cookies)
        if response.status_code == 404:
            raise NpoNotFoundError("NPO Start does not know this programme")
        if response.status_code == 402:
            raise NpoSubscriptionError("Only NPO Plus subscribers can watch this programme")
        if response.status_code == 429:
            raise NpoError("NPO Start asked VODLoft to slow down; try again later")
        if response.status_code >= 400:
            raise NpoError(f"NPO Start answered with HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise NpoError("NPO Start returned something that is not JSON") from exc

    def get(self, endpoint: str, *, cookies=None, **params) -> Any:
        query = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items() if value is not None}
        return self._send("GET", f"{API}/{endpoint}", params=query, cookies=cookies)

    def search(self, query: str, search_type: str) -> list[dict]:
        data = self.get(
            "search-collection-items", searchType=search_type, partyId=1, searchQuery=query,
            subscriptionType="anonymous", includePremiumContent=True,
        )
        items = data.get("items") if isinstance(data, dict) else None
        return [item for item in items or [] if isinstance(item, dict)]

    def series_detail(self, slug: str) -> dict:
        return _object(self.get("series-detail", slug=slug, includePremiumContent=True))

    def series_seasons(self, slug: str, series_type: str | None) -> list[dict]:
        return _list(self.get("series-seasons", slug=slug, type=series_type, includePremiumContent=True))

    def programs_by_season(self, guid: str) -> list[dict]:
        return _list(self.get("programs-by-season", guid=guid, sort="firstBroadcastDate", includePremiumContent=True))

    def program_detail(self, slug: str) -> dict:
        return _object(self.get("program-detail", slug=slug, ageRestriction="undefined", includePremiumContent=True))

    def session(self) -> dict:
        """The npo.nl sign-in the cookies file holds: empty when it no longer signs anyone in."""
        cookies = account.load_cookies()
        if cookies is None:
            return {}
        data = self._send("GET", SESSION, cookies=cookies)
        return data if isinstance(data, dict) else {}

    def stream_link(self, product_id: str, referrer_url: str) -> dict:
        """The HLS stream NPO's player would play. A clear stream needs no headers to download.

        With a signed-in npo.nl session, the player is asked as that account,
        so programmes its subscription unlocks get a stream too.
        """
        token = _object(self.get("player-token", productId=product_id, cookies=account.load_cookies())).get("jwt")
        if not isinstance(token, str) or not token:
            raise NpoError("NPO Start gave no player token")
        return _object(self._send(
            "POST", STREAM_LINK, json={"profileName": "hls", "referrerUrl": referrer_url},
            headers={"Authorization": token, "Origin": ORIGIN, "Referer": f"{ORIGIN}/"},
        ))


def _object(data: Any) -> dict:
    if not isinstance(data, dict):
        raise NpoError("NPO Start returned an unexpected answer")
    return data


def _list(data: Any) -> list[dict]:
    if not isinstance(data, list):
        raise NpoError("NPO Start returned an unexpected answer")
    return [item for item in data if isinstance(item, dict)]
