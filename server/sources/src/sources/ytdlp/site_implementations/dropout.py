"""How yt-dlp signs in on Dropout: with the account's email and password on its sign-in page, as a browser does.
Dropout's session cookie runs out, so VODLoft keeps the email address and password to sign in again before it does."""
from __future__ import annotations

import re
from collections.abc import Mapping

from ...contract import SignInRejected
from ...site_accounts import SignedIn
from . import web_sign_in
from .other_sites import OtherSitesImplementation

_LOGIN_URL = "https://watch.dropout.tv/login"
_TOKEN = re.compile(r"""name=["']authenticity_token["'] value=["'](.+?)["']""")
_SUBSCRIBED = re.compile(r"""user_has_subscription:\s*["'](.+?)["']""")


class DropoutImplementation(OtherSitesImplementation):
    key = "dropout"

    def sign_in(self, values: Mapping[str, str]) -> SignedIn:
        email, password = web_sign_in.credentials(values)
        session = web_sign_in.browser()
        page = web_sign_in.answer(self.site.name, lambda: session.get(_LOGIN_URL, timeout=web_sign_in.TIMEOUT_SECONDS))
        token = _TOKEN.search(page.text)
        if not page.ok or token is None:
            raise SignInRejected(f"Dropout's sign-in page did not open (it answered {page.status_code}). Try again later.")
        response = web_sign_in.answer(self.site.name, lambda: session.post(_LOGIN_URL, data={
            "email": email, "password": password, "authenticity_token": token.group(1), "utf8": "✓",
        }, timeout=web_sign_in.TIMEOUT_SECONDS))
        subscribed = _SUBSCRIBED.search(response.text)
        if subscribed is None:
            raise SignInRejected("Dropout does not accept this email address and password.", web_sign_in.PASSWORD)
        if subscribed.group(1).lower() != "true":
            raise SignInRejected("This Dropout account has no subscription, which Dropout's videos need.", web_sign_in.EMAIL)
        return web_sign_in.signed_in(session, ("dropout.tv",), email, password)

    def renew_sign_in(self, signed_in: SignedIn) -> SignedIn:
        return self.sign_in(signed_in.secrets)
