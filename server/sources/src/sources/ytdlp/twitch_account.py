"""Signing in on Twitch with a code, the way Twitch's TV app does: VODLoft shows a code, the user enters it at
twitch.tv/activate, and Twitch gives a token for the account.

The token is for the client ID of Twitch's TV app, the one yt-dlp sends Twitch's own API (GQL) with, so yt-dlp can
use it in place of the ``auth-token`` cookie of a browser. Twitch gives that app no refresh token VODLoft could use,
so the sign-in lasts as long as Twitch keeps the token; VODLoft asks Twitch every hour whether it still does, as
Twitch asks apps to.
"""
from __future__ import annotations

import time
from collections.abc import Callable

import requests

from ..contract import DeviceCode, SignInCodeEnded, SignInRejected
from ..site_accounts import SignedIn, cookie_line

CLIENT_ID = "ue6666qo983tsx6so1t0vnawi233wa"
"""The client ID of Twitch's TV app, which yt-dlp's Twitch extractor sends as well."""
_DEVICE_URL = "https://id.twitch.tv/oauth2/device"
_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
_TIMEOUT_SECONDS = 15
_CHECK_EVERY_SECONDS = 60 * 60
# yt-dlp reads the token from the cookie Twitch's website keeps it in.
_TOKEN_COOKIE = "auth-token"
_TOKEN = "access_token"


def _answer(ask: Callable[[], requests.Response]) -> requests.Response:
    try:
        return ask()
    except requests.RequestException:
        raise SignInRejected("Could not reach Twitch. Try again in a moment.") from None


def _message(response: requests.Response) -> str:
    try:
        return str(response.json().get("message") or "")
    except ValueError:
        return ""


def start() -> DeviceCode:
    response = _answer(lambda: requests.post(_DEVICE_URL, data={"client_id": CLIENT_ID, "scopes": ""}, timeout=_TIMEOUT_SECONDS))
    if not response.ok:
        raise SignInRejected(f"Twitch gave no code ({_message(response) or response.status_code}). Try again later.")
    data = response.json()
    return DeviceCode(
        device_code=str(data["device_code"]), user_code=str(data["user_code"]),
        verification_url=str(data.get("verification_uri") or "https://www.twitch.tv/activate"),
        expires_in=int(data.get("expires_in") or 1800), interval=max(int(data.get("interval") or 5), 1),
    )


def _check(token: str) -> tuple[str | None, int]:
    """The login of the account the token is for, and the seconds Twitch keeps it. Raises SignInRejected once
    Twitch no longer accepts it."""
    response = _answer(lambda: requests.get(_VALIDATE_URL, headers={"Authorization": f"OAuth {token}"}, timeout=_TIMEOUT_SECONDS))
    if response.status_code == 401:
        raise SignInRejected("Twitch ended the sign-in. Sign in again with a new code.")
    if not response.ok:
        raise SignInRejected(f"Twitch answered {response.status_code}. VODLoft tries again later.")
    data = response.json()
    return (str(data.get("login") or "") or None), int(data.get("expires_in") or 0)


def _signed_in(token: str) -> SignedIn:
    account, expires_in = _check(token)
    now = time.time()
    ends = now + expires_in if expires_in else None
    return SignedIn(
        cookies=(cookie_line("twitch.tv", _TOKEN_COOKIE, token, ends),), account=account, secrets={_TOKEN: token},
        renew_at=min(now + _CHECK_EVERY_SECONDS, ends) if ends else now + _CHECK_EVERY_SECONDS,
    )


def finish(code: DeviceCode, stop: Callable[[float], bool]) -> SignedIn:
    """Ask Twitch every ``interval`` until the user entered the code."""
    ends = time.monotonic() + code.expires_in
    interval = code.interval
    while time.monotonic() < ends:
        if stop(interval):
            raise SignInCodeEnded("Signing in was cancelled.")
        response = _answer(lambda: requests.post(_TOKEN_URL, data={
            "client_id": CLIENT_ID, "scopes": "", "device_code": code.device_code, "grant_type": _GRANT,
        }, timeout=_TIMEOUT_SECONDS))
        if response.ok:
            token = str(response.json().get(_TOKEN) or "")
            if not token:
                raise SignInRejected("Twitch signed in, but gave no token. Try again later.")
            return _signed_in(token)
        message = _message(response)
        if message == "authorization_pending":
            continue
        if message == "slow_down":
            interval += 5
            continue
        if message == "invalid device code":
            raise SignInCodeEnded("The code ran out or was turned down. Start again for a new code.")
        raise SignInRejected(f"Twitch did not sign in ({message or response.status_code}). Try again later.")
    raise SignInCodeEnded("The code ran out before it was entered. Start again for a new code.")


def renew(signed_in: SignedIn) -> SignedIn:
    """The sign-in once Twitch said it still accepts its token."""
    token = signed_in.secrets.get(_TOKEN)
    if not token:
        raise SignInRejected("Sign in on Twitch again with a new code.")
    return _signed_in(token)
