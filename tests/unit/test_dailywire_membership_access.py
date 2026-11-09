from __future__ import annotations

import pytest

from sources import get_source
from sources.dailywire import membership
from sources.dailywire.api.types.user_info import DwMembershipLevel


@pytest.fixture(autouse=True)
def _forget():
    membership.forget_level()
    yield
    membership.forget_level()


def _signed_in_at(monkeypatch, level, calls=None):
    def look_up():
        if calls is not None:
            calls.append(level)
        return level, False

    monkeypatch.setattr(membership, "_look_up", look_up)


@pytest.mark.parametrize(("level", "key", "expected"), [
    (DwMembershipLevel.INSIDER, "INSIDER", True),
    (DwMembershipLevel.ALL_ACCESS, "INSIDER_PLUS", True),
    (DwMembershipLevel.INSIDER, "ALL_ACCESS", None),
    (DwMembershipLevel.FREE, "INSIDER", None),
    (None, "INSIDER", None),
])
def test_the_signed_in_level_gives_the_levels_up_to_it(monkeypatch, level, key, expected):
    _signed_in_at(monkeypatch, level)

    assert get_source("dailywire").has_access(key) is expected


def test_the_level_is_asked_once_until_the_sign_in_changes(monkeypatch):
    calls: list = []
    _signed_in_at(monkeypatch, DwMembershipLevel.INSIDER, calls)
    source = get_source("dailywire")

    source.has_access("INSIDER")
    source.has_access("ALL_ACCESS")
    assert len(calls) == 1

    membership.forget_level()
    source.has_access("INSIDER")
    assert len(calls) == 2


def test_a_failed_lookup_keeps_the_last_answer(monkeypatch):
    _signed_in_at(monkeypatch, DwMembershipLevel.INSIDER)
    membership.account_level()
    monkeypatch.setattr(membership, "_checked_at", 0.0)
    monkeypatch.setattr(membership, "_look_up", lambda: (None, True))

    assert membership.account_level() is DwMembershipLevel.INSIDER


def test_granted_media_shows_an_open_lock_but_refused_media_stays_locked(monkeypatch):
    from datetime import datetime, timezone

    from backend.services.media_access import access_granted, access_locked

    _signed_in_at(monkeypatch, DwMembershipLevel.INSIDER)

    assert access_granted("dailywire", "INSIDER", None) is True
    assert access_locked("dailywire", "INSIDER", None) is False
    assert access_granted("dailywire", "INSIDER", datetime.now(timezone.utc)) is False
    assert access_granted("dailywire", None, None) is False
