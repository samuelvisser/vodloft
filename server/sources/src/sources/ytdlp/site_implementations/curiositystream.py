"""How yt-dlp signs in on CuriosityStream: with the account's email and password, which CuriosityStream trades for
a token that lasts until the user signs out."""
from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import quote

from ...contract import SignInRejected
from ...site_accounts import SignedIn, cookie_line
from . import web_sign_in
from .other_sites import OtherSitesImplementation

_LOGIN_URL = "https://api.curiositystream.com/v1/login"
# yt-dlp reads the token from the cookie CuriosityStream's website keeps it in, quoted.
_TOKEN_COOKIE = "auth_token"


def _refusal(data: dict) -> str | None:
    """What CuriosityStream said when it did not sign in."""
    message = (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else data.get("error")
    if isinstance(message, dict):
        message = " ".join(str(part) for parts in message.values() for part in (parts if isinstance(parts, list) else [parts]))
    return str(message) if message else None


class CuriosityStreamImplementation(OtherSitesImplementation):
    key = "curiositystream"

    def sign_in(self, values: Mapping[str, str]) -> SignedIn:
        email, password = web_sign_in.credentials(values)
        session = web_sign_in.browser()
        response = web_sign_in.answer(self.site.name, lambda: session.post(
            _LOGIN_URL, data={"email": email, "password": password}, timeout=web_sign_in.TIMEOUT_SECONDS,
        ))
        try:
            data = response.json()
        except ValueError:
            data = {}
        data = data if isinstance(data, dict) else {}
        token = str(((data.get("message") or {}) if isinstance(data.get("message"), dict) else {}).get("auth_token") or "")
        if token:
            return SignedIn(cookies=(cookie_line("curiositystream.com", _TOKEN_COOKIE, quote(token, safe="")),), account=email)
        if (refusal := _refusal(data)) or response.status_code in (400, 401, 403):
            raise SignInRejected(refusal or "CuriosityStream does not accept this email address and password.", web_sign_in.PASSWORD)
        raise SignInRejected(f"CuriosityStream answered {response.status_code}. Try again later.")
