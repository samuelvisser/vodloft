"""Signing in on a Site's website the way a browser does, for the Sites whose implementation signs in with the
user's email and password: the cookies the Site sets become the sign-in yt-dlp uses."""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping

import requests

from ...contract import SignInRejected
from ...site_accounts import SignedIn, cookie_line

BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
TIMEOUT_SECONDS = 20
RENEW_BEFORE_SECONDS = 2 * 24 * 60 * 60
"""How long before its cookies run out a sign-in signs in again."""
RENEW_AFTER_SECONDS = 30 * 24 * 60 * 60
"""How long a sign-in whose cookies tell no end lasts before it signs in again."""
EMAIL = "email"
PASSWORD = "password"


def browser() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER, "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"})
    return session


def answer(site_name: str, ask: Callable[[], requests.Response]) -> requests.Response:
    """What the Site answered, or SignInRejected when it could not be reached."""
    try:
        return ask()
    except requests.RequestException:
        raise SignInRejected(f"Could not reach {site_name}. Try again in a moment.") from None


def credentials(values: Mapping[str, str]) -> tuple[str, str]:
    """The email address and password filled in. Raises SignInRejected for one left empty."""
    email, password = (values.get(EMAIL) or "").strip(), values.get(PASSWORD) or ""
    if not email:
        raise SignInRejected("Fill in your email address", EMAIL)
    if not password:
        raise SignInRejected("Fill in your password", PASSWORD)
    return email, password


def signed_in(session: requests.Session, domains: Iterable[str], email: str, password: str) -> SignedIn:
    """The sign-in of the cookies the Site set on its ``domains``, which signs in again with the email address and
    password a little before the first of them runs out."""
    own = tuple(domains)
    cookies = [
        cookie for cookie in session.cookies
        if any(cookie.domain.lstrip(".") == domain or cookie.domain.lstrip(".").endswith(f".{domain}") for domain in own)
    ]
    ends = [cookie.expires for cookie in cookies if cookie.expires]
    renew_at = min(ends) - RENEW_BEFORE_SECONDS if ends else time.time() + RENEW_AFTER_SECONDS
    return SignedIn(
        cookies=tuple(cookie_line(cookie.domain.lstrip("."), cookie.name, cookie.value or "", cookie.expires) for cookie in cookies),
        account=email,
        secrets={EMAIL: email, PASSWORD: password},
        renew_at=max(renew_at, time.time() + 60 * 60),
    )
