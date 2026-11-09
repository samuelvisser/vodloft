"""The membership level of the Daily Wire account VODLoft is signed in with.

The Daily Wire tells it when asked, so the answer is kept for half an hour, and forgotten
as soon as the stored sign-in changes.
"""
from __future__ import annotations

import logging
import threading
import time

from .api.types.user_info import DwMembershipLevel

logger = logging.getLogger(__name__)

# The Daily Wire's levels, each giving everything the ones before it give.
LEVEL_ORDER = (
    DwMembershipLevel.FREE,
    DwMembershipLevel.READER,
    DwMembershipLevel.INSIDER,
    DwMembershipLevel.INSIDER_PLUS,
    DwMembershipLevel.ALL_ACCESS,
)

_CHECK_SECONDS = 30 * 60
# When The Daily Wire could not be asked, it is asked again sooner.
_RETRY_SECONDS = 5 * 60
_LOOKUP_TIMEOUT_SECONDS = 10.0

_lock = threading.Lock()
_level: DwMembershipLevel | None = None
_checked_at: float | None = None
_retry_at: float | None = None


def account_level() -> DwMembershipLevel | None:
    """The signed-in account's membership level, or None when VODLoft is not signed in or does not know it."""
    global _level, _checked_at, _retry_at
    now = time.monotonic()
    with _lock:
        if _checked_at is not None and now - _checked_at < (_RETRY_SECONDS if _retry_at else _CHECK_SECONDS):
            return _level
    level, failed = _look_up()
    with _lock:
        if not failed:
            _level = level
        _checked_at = time.monotonic()
        _retry_at = _checked_at if failed else None
        return _level


def _look_up() -> tuple[DwMembershipLevel | None, bool]:
    """The level The Daily Wire names for the signed-in account, and whether asking failed."""
    from .api.dw_api.client import MiddlewareClient
    from .auth import DeviceAuthClient

    try:
        if DeviceAuthClient().get_token() is None:
            return None, False
        info = MiddlewareClient(request_priority="interactive", request_timeout=_LOOKUP_TIMEOUT_SECONDS).get_user_info()
    except Exception as exc:  # noqa: BLE001 - an unreachable Daily Wire must not break what asks
        logger.info("Could not ask The Daily Wire for the account's membership level: %s", exc)
        return None, True
    return (info.access_level if isinstance(info.access_level, DwMembershipLevel) else None), False


def gives(level: DwMembershipLevel | None, needed: str) -> bool:
    """Whether an account at ``level`` may watch what needs the membership level ``needed``."""
    try:
        wanted = DwMembershipLevel(needed)
    except ValueError:
        return False
    return level in LEVEL_ORDER and wanted in LEVEL_ORDER and LEVEL_ORDER.index(level) >= LEVEL_ORDER.index(wanted)


def forget_level() -> None:
    """The stored sign-in changed, so the next question asks The Daily Wire again."""
    global _level, _checked_at, _retry_at
    with _lock:
        _level = None
        _checked_at = None
        _retry_at = None
