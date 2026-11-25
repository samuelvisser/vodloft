"""How yt-dlp signs in on Niconico: with the account's email address or phone number and password on its sign-in
page, as a browser does. Niconico's session cookie runs out, so VODLoft keeps them to sign in again before it does."""
from __future__ import annotations

import html
import re
from collections.abc import Mapping

from ...contract import SignInRejected
from ...site_accounts import SignedIn
from . import web_sign_in
from .other_sites import OtherSitesImplementation

_ACCOUNTS = "https://account.nicovideo.jp"
_SESSION_COOKIE = "user_session"
_NOTICE = re.compile(r"""class=["'][^"']*notice__text[^"']*["'][^>]*>(.*?)</""", re.S)


class NiconicoImplementation(OtherSitesImplementation):
    key = "niconico"

    def sign_in(self, values: Mapping[str, str]) -> SignedIn:
        email, password = web_sign_in.credentials(values)
        session = web_sign_in.browser()
        web_sign_in.answer(self.site.name, lambda: session.get(f"{_ACCOUNTS}/login", timeout=web_sign_in.TIMEOUT_SECONDS))
        response = web_sign_in.answer(self.site.name, lambda: session.post(
            f"{_ACCOUNTS}/login/redirector", data={"mail_tel": email, "password": password},
            headers={"Referer": f"{_ACCOUNTS}/login"}, timeout=web_sign_in.TIMEOUT_SECONDS,
        ))
        if any(cookie.name == _SESSION_COOKIE for cookie in session.cookies):
            return web_sign_in.signed_in(session, ("nicovideo.jp",), email, password)
        if "oneTimePw" in response.text:
            raise SignInRejected(
                "Your Niconico account asks for a one-time code when it signs in, which VODLoft can't fill in. "
                "Sign in with a cookies file instead.",
            )
        notice = _NOTICE.search(response.text)
        message = html.unescape(re.sub(r"<[^>]+>", "", notice.group(1))).strip() if notice else ""
        raise SignInRejected(message or "Niconico does not accept this email address or phone number and password.", web_sign_in.PASSWORD)

    def renew_sign_in(self, signed_in: SignedIn) -> SignedIn:
        return self.sign_in(signed_in.secrets)
