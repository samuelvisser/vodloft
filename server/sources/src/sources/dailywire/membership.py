"""The membership level of the Daily Wire account VODLoft is signed in with.

VODLoft keeps the level beside the sign-in and does not ask for it on a schedule. It learns
it when the account signs in, whenever the account's details are looked up, and again when
The Daily Wire refuses a download for lack of a level while the sign-in is still valid.
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

_STORE_KEY = "membership_level"
_LOOKUP_TIMEOUT_SECONDS = 10.0
# A sign-in this close to running out is renewed before it is used, so it is not checked with.
_RENEW_MARGIN_SECONDS = 60

_lock = threading.Lock()
_loaded = False
_level: DwMembershipLevel | None = None


def account_level() -> DwMembershipLevel | None:
    """The level kept for the signed-in account, or None when VODLoft does not know it. Never asks The Daily Wire."""
    global _loaded, _level
    with _lock:
        if not _loaded:
            _level = _read()
            _loaded = True
        return _level


def remember_level(level: DwMembershipLevel | str | None) -> None:
    """Keep the level The Daily Wire named for the signed-in account; None forgets it."""
    global _loaded, _level
    known = level if isinstance(level, DwMembershipLevel) else None
    with _lock:
        _level, _loaded = known, True
        try:
            from .auth import TokenStore

            store = TokenStore()
            if known is None:
                store.delete(_STORE_KEY)
            else:
                store.store_record(_STORE_KEY, known.value)
        except Exception as exc:  # noqa: BLE001 - the level is a nicety; the sign-in itself still works
            logger.info("Could not keep the Daily Wire membership level: %s", exc)


def look_up_level() -> None:
    """Ask The Daily Wire for the signed-in account's level and keep it. The lookup keeps it itself."""
    from .api.dw_api.client import MiddlewareClient

    try:
        MiddlewareClient(request_priority="interactive", request_timeout=_LOOKUP_TIMEOUT_SECONDS).get_user_info()
    except Exception as exc:  # noqa: BLE001 - an unreachable Daily Wire must not break what asks
        logger.info("Could not ask The Daily Wire for the account's membership level: %s", exc)


def check_after_refusal() -> None:
    """The Daily Wire refused a download for lack of a level: ask again whether the account's level changed,
    but only while the sign-in is valid without renewing it, so a refusal never renews the sign-in."""
    from .auth import DeviceAuthClient

    try:
        client = DeviceAuthClient()
        record = client.store.load(client.make_store_key())
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not read the Daily Wire sign-in: %s", exc)
        return
    if record is None or record.expires_at - time.time() <= _RENEW_MARGIN_SECONDS:
        return
    look_up_level()


def gives(level: DwMembershipLevel | None, needed: str) -> bool:
    """Whether an account at ``level`` may watch what needs the membership level ``needed``."""
    try:
        wanted = DwMembershipLevel(needed)
    except ValueError:
        return False
    return level in LEVEL_ORDER and wanted in LEVEL_ORDER and LEVEL_ORDER.index(level) >= LEVEL_ORDER.index(wanted)


def _read() -> DwMembershipLevel | None:
    try:
        from .auth import TokenStore

        stored = TokenStore().load_record(_STORE_KEY)
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not read the Daily Wire membership level: %s", exc)
        return None
    try:
        return DwMembershipLevel(stored) if stored else None
    except ValueError:
        return None
