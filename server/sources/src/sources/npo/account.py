"""The npo.nl session VODLoft signs in with: a cookies file exported from a signed-in browser.

VODLoft never sees the NPO password. The cookies only go along when NPO's
player is asked for a stream, so the catalogue is still read as an anonymous
visitor.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from http.cookiejar import MozillaCookieJar
from pathlib import Path

from config.settings.base import get_config_path

from .. import cookies as cookie_files

logger = logging.getLogger(__name__)

_DOMAIN = "npo.nl"


def cookies_path() -> Path:
    return get_config_path().parent / "npo" / "cookies.txt"


def has_cookies() -> bool:
    return cookies_path().is_file()


def save_cookies(content: bytes) -> None:
    """Store the cookies file. Raises ValueError when it holds no npo.nl cookies."""
    text = cookie_files.cookies_text(content)
    if not any(_npo_cookie(line) for line in text.splitlines()):
        raise ValueError("This cookies file has no npo.nl cookies. Export it while signed in on npo.nl.")
    cookie_files.store(cookies_path(), text)
    forget_status()


def remove_cookies() -> None:
    cookies_path().unlink(missing_ok=True)
    forget_status()


def load_cookies() -> MozillaCookieJar | None:
    return cookie_files.load(cookies_path())


def _npo_cookie(line: str) -> bool:
    fields = line.split("\t")
    if len(fields) < 7:
        return False
    domain = fields[0].removeprefix("#HttpOnly_").lstrip(".").lower()
    return domain == _DOMAIN or domain.endswith(f".{_DOMAIN}")


@dataclass(frozen=True)
class AccountStatus:
    """What npo.nl says about the signed-in account."""

    signed_in: bool
    subscription: bool
    expires_at: datetime | None = None
    checked_at: float = 0.0


_CHECK_SECONDS = 30 * 60
_lock = threading.Lock()
_status: AccountStatus | None = None


def status(client, *, refresh: bool = False) -> AccountStatus | None:
    """The account the cookies file signs in, checked with npo.nl at most every half hour.

    None without a cookies file. When npo.nl cannot be asked, the last answer
    stands, and before any answer the cookies are trusted.
    """
    global _status
    if not has_cookies():
        _status = None
        return None
    with _lock:
        if not refresh and _status is not None and time.monotonic() - _status.checked_at < _CHECK_SECONDS:
            return _status
    try:
        session = client.session()
    except Exception as exc:  # noqa: BLE001 - an unreachable npo.nl must not hide the sign-in
        logger.info("Could not check the NPO sign-in: %s", exc)
        return _status or AccountStatus(signed_in=True, subscription=True)
    # An anonymous visitor gets an empty session; NPO names the subscription at the
    # top of a signed-in one, and some versions inside its user.
    user = session.get("user") if isinstance(session.get("user"), dict) else {}
    signed_in = bool(session.get("user") or session.get("expires"))
    with _lock:
        _status = AccountStatus(
            signed_in=signed_in,
            subscription=signed_in and True in (session.get("hasSubscription"), user.get("hasSubscription")),
            expires_at=_datetime(session.get("expires")),
            checked_at=time.monotonic(),
        )
        return _status


def forget_status() -> None:
    global _status
    with _lock:
        _status = None


def _datetime(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
