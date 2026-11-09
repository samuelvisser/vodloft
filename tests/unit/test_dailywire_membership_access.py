from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from sources import get_source
from sources.dailywire import membership
from sources.dailywire.api.types.user_info import DwMembershipLevel
from sources.dailywire.auth.config import OAuthTokens


@pytest.fixture
def keyring_store(monkeypatch):
    import keyring

    stored: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, key: stored.get((service, key)))
    monkeypatch.setattr(keyring, "set_password", lambda service, key, value: stored.__setitem__((service, key), value))
    monkeypatch.setattr(keyring, "delete_password", lambda service, key: stored.pop((service, key), None))
    monkeypatch.setattr(membership, "_loaded", False)
    monkeypatch.setattr(membership, "_level", None)
    return stored


@pytest.fixture
def lookups(monkeypatch):
    """Each lookup at The Daily Wire, which answers with the level in ``answer``."""
    calls: list[DwMembershipLevel] = []
    answer = {"level": DwMembershipLevel.INSIDER}

    def look_up():
        calls.append(answer["level"])
        membership.remember_level(answer["level"])

    monkeypatch.setattr(membership, "look_up_level", look_up)
    return calls, answer


def _sign_in(keyring_store, *, expires_in: float) -> None:
    from sources.dailywire.auth import DeviceAuthClient, TokenStore

    TokenStore().save(DeviceAuthClient().make_store_key(), OAuthTokens("a", "r", "Bearer", time.time() + expires_in))


@pytest.mark.parametrize(("level", "key", "expected"), [
    (DwMembershipLevel.INSIDER, "INSIDER", True),
    (DwMembershipLevel.ALL_ACCESS, "INSIDER_PLUS", True),
    (DwMembershipLevel.INSIDER, "ALL_ACCESS", None),
    (DwMembershipLevel.FREE, "INSIDER", None),
    (None, "INSIDER", None),
])
def test_the_kept_level_gives_the_levels_up_to_it(keyring_store, level, key, expected):
    membership.remember_level(level)

    assert get_source("dailywire").has_access(key) is expected


def test_the_level_is_kept_beside_the_sign_in_and_never_asked_for_on_its_own(keyring_store, lookups):
    calls, _ = lookups
    membership.remember_level(DwMembershipLevel.INSIDER)
    membership._loaded = False

    for _ in range(3):
        assert get_source("dailywire").has_access("INSIDER") is True
    assert calls == []


def test_a_refused_download_asks_again_while_the_sign_in_is_valid(keyring_store, lookups):
    calls, answer = lookups
    _sign_in(keyring_store, expires_in=3600)
    membership.remember_level(DwMembershipLevel.INSIDER)
    answer["level"] = DwMembershipLevel.FREE

    get_source("dailywire").download_refused("INSIDER")

    assert calls == [DwMembershipLevel.FREE]
    assert get_source("dailywire").has_access("INSIDER") is None


@pytest.mark.parametrize("expires_in", [30, -60])
def test_a_refused_download_does_not_ask_when_the_sign_in_needs_renewing(keyring_store, lookups, expires_in):
    calls, _ = lookups
    _sign_in(keyring_store, expires_in=expires_in)

    get_source("dailywire").download_refused("INSIDER")

    assert calls == []


def test_a_refusal_for_something_else_does_not_ask(keyring_store, lookups):
    calls, _ = lookups
    _sign_in(keyring_store, expires_in=3600)

    get_source("dailywire").download_refused("npo_plus")

    assert calls == []


def test_signing_out_forgets_the_level(keyring_store):
    from sources.dailywire.auth import DeviceAuthClient

    _sign_in(keyring_store, expires_in=3600)
    membership.remember_level(DwMembershipLevel.INSIDER)

    DeviceAuthClient().revoke()

    assert membership.account_level() is None
    assert not any(key == "membership_level" for _, key in keyring_store)


def test_granted_media_shows_an_open_lock_but_refused_media_stays_locked(keyring_store):
    from backend.services.media_access import access_granted, access_locked

    membership.remember_level(DwMembershipLevel.INSIDER)

    assert access_granted("dailywire", "INSIDER", None) is True
    assert access_locked("dailywire", "INSIDER", None) is False
    assert access_granted("dailywire", "INSIDER", datetime.now(timezone.utc)) is False
    assert access_granted("dailywire", None, None) is False


def test_the_background_migration_learns_the_level_of_an_existing_sign_in(keyring_store, lookups):
    import asyncio
    import importlib

    calls, _ = lookups
    migration = importlib.import_module(
        "backend.db.background_migrations.versions.c85008e6cb25_learn_signed_in_access",
    )

    class Context:
        def update_progress(self, *args):
            pass

        def raise_if_canceled(self):
            pass

    asyncio.run(migration.migrate(Context()))

    assert calls == [DwMembershipLevel.INSIDER]
    assert get_source("dailywire").has_access("INSIDER") is True


def test_the_level_the_daily_wire_gives_as_text_is_kept(keyring_store, monkeypatch):
    from sources.dailywire.api.dw_api.client import MiddlewareClient
    from sources.dailywire.auth import DeviceAuthClient

    _sign_in(keyring_store, expires_in=3600)
    payload = {
        "personId": "p", "subscriptionId": "s", "recurlyAccountCode": "r", "username": "u", "email": "e",
        "firstName": "f", "lastName": "l", "avatar": "a", "accessLevel": "ALL_ACCESS", "planType": "t",
        "accountCreatedAt": "2024-01-01T00:00:00Z",
    }
    monkeypatch.setattr(MiddlewareClient, "_get", lambda self, *args, **kwargs: payload)
    assert DeviceAuthClient().get_token() is not None

    membership.look_up_level()

    assert membership.account_level() is DwMembershipLevel.ALL_ACCESS
    membership._loaded = False
    assert get_source("dailywire").has_access("INSIDER") is True
