"""How yt-dlp signs in on Nebula: with the account's email and password, which Nebula trades for a token that lasts
until the user signs out."""
from __future__ import annotations

from collections.abc import Mapping

from ...contract import SignInRejected
from ...site_accounts import SignedIn, cookie_line
from . import web_sign_in
from .other_sites import OtherSitesImplementation

_LOGIN_URL = "https://nebula.tv/auth/login/"
# yt-dlp reads the token from the cookie Nebula's website keeps it in.
_TOKEN_COOKIE = "nebula_auth.apiToken"


class NebulaImplementation(OtherSitesImplementation):
    key = "nebula"

    def sign_in(self, values: Mapping[str, str]) -> SignedIn:
        email, password = web_sign_in.credentials(values)
        session = web_sign_in.browser()
        response = web_sign_in.answer(self.site.name, lambda: session.post(
            _LOGIN_URL, json={"email": email, "password": password}, timeout=web_sign_in.TIMEOUT_SECONDS,
        ))
        if response.status_code in (400, 401, 403):
            raise SignInRejected("Nebula does not accept this email address and password.", web_sign_in.PASSWORD)
        if not response.ok:
            raise SignInRejected(f"Nebula answered {response.status_code}. Try again later.")
        token = str((response.json() or {}).get("key") or "")
        if not token:
            raise SignInRejected("Nebula signed in, but gave no token. Try again later.")
        return SignedIn(cookies=(cookie_line("nebula.tv", _TOKEN_COOKIE, token),), account=email)
