"""Messages and actions: which rules want an event, grouping, repeats, sending, destinations and the rules API."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path, monkeypatch):
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base
    from config import get_settings

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    yield session
    session.close()
    engine.dispose()


def _collection(session, slug="show", *, added_by_id=None, source_key="ytdlp"):
    from backend.db.models import Collection

    collection = Collection(
        source_key=source_key, uuid=f"{slug}-uuid", slug=slug, title=slug.title(), description=None,
        sharing_url=f"https://www.youtube.com/@{slug}", membership_level="FREE", type="series",
        episode_identifier="date_based", author_name="Host", author_slug="host", added_by_id=added_by_id,
    )
    session.add(collection)
    session.flush()
    return collection


def _rule(session, event, **values):
    from backend.db.models import NotificationRule

    rule = NotificationRule(**{
        "position": 1, "personal": False, "enabled": True, "event": event, "collection_scope": "any",
        "collection_ids": [], "push": True, "destination_ids": [], "delivery": "now", "summary_time": "08:00",
        **values,
    })
    session.add(rule)
    session.flush()
    return rule


def _device(session, user_id=None, name="Phone"):
    from backend.db.models import PushSubscription

    device = PushSubscription(user_id=user_id, endpoint_hash=f"hash-{name}-{user_id}", encrypted_subscription="x", device_name=name)
    session.add(device)
    session.flush()
    return device


def _deliveries(session):
    from backend.db.models import NotificationDelivery

    return list(session.scalars(select(NotificationDelivery).order_by(NotificationDelivery.id)))


def _emit(session, event, **values):
    from backend.services.notifications import emit

    return emit(session, event, **{"title": "Something", "occurred_at": NOW, **values})


def test_default_rules_come_back_without_doubling(db):
    from backend.db.models import NotificationRule
    from backend.services.notifications.rules import DEFAULT_RULES, restore_default_rules

    assert restore_default_rules(db) == len(DEFAULT_RULES)
    first = db.scalar(select(NotificationRule).where(NotificationRule.default_key == "download_failed"))
    db.delete(first)
    db.flush()
    assert restore_default_rules(db) == 1
    assert restore_default_rules(db) == 0
    daily = db.scalar(select(NotificationRule).where(NotificationRule.default_key == "daily_summary"))
    assert (daily.enabled, daily.delivery, daily.event) == (False, "daily", "everything")


def test_a_problem_is_pushed_to_administrator_devices_once_a_day(db):
    from backend.services.notifications import Event

    _rule(db, "download_failed")
    _device(db)
    _emit(db, Event.DOWNLOAD_FAILED, dedupe_key="same")
    _emit(db, Event.DOWNLOAD_FAILED, dedupe_key="same", occurred_at=NOW + timedelta(hours=2))
    assert len(_deliveries(db)) == 1
    _emit(db, Event.DOWNLOAD_FAILED, dedupe_key="same", occurred_at=NOW + timedelta(days=1, minutes=1))
    assert len(_deliveries(db)) == 2


def test_new_downloads_of_one_collection_go_out_as_one_message(db):
    from backend.services.notifications import Event
    from backend.services.notifications.delivery import _batches, compose

    collection = _collection(db)
    _rule(db, "episode_downloaded")
    _device(db)
    for number in range(3):
        _emit(db, Event.EPISODE_DOWNLOADED, title=f"Downloaded: {number}", collection_id=collection.id,
              data={"collection": "Show"}, occurred_at=NOW + timedelta(seconds=number))
    assert not _batches(db, NOW + timedelta(seconds=30))
    batches = _batches(db, NOW + timedelta(minutes=2))
    assert len(batches) == 1
    message = compose(batches[0].events, daily=False)
    assert message.title == "3 new downloads in Show"
    assert "• Downloaded: 0" in message.body


def test_a_rule_for_chosen_collections_skips_the_rest(db):
    from backend.services.notifications import Event

    chosen, other = _collection(db, "chosen"), _collection(db, "other")
    _rule(db, "episode_downloaded", collection_scope="chosen", collection_ids=[chosen.id])
    _device(db)
    _emit(db, Event.EPISODE_DOWNLOADED, collection_id=other.id)
    assert not _deliveries(db)
    _emit(db, Event.EPISODE_DOWNLOADED, collection_id=chosen.id)
    assert len(_deliveries(db)) == 1


def test_a_quick_download_only_reaches_whoever_asked(db):
    from backend.db.models import User
    from backend.services.notifications import Event

    alice, bob = User(username="alice", password_hash="x"), User(username="bob", password_hash="x")
    db.add_all([alice, bob])
    db.flush()
    _rule(db, "quick_download_finished", personal=True, user_id=alice.id)
    _rule(db, "quick_download_finished", personal=True, user_id=bob.id)
    alice_phone, _ = _device(db, alice.id, "Alice"), _device(db, bob.id, "Bob")
    _emit(db, Event.QUICK_DOWNLOAD_FINISHED, user_id=alice.id)
    assert [delivery.subscription_id for delivery in _deliveries(db)] == [alice_phone.id]


def test_collections_i_added_only_counts_my_own(db):
    from backend.db.models import User
    from backend.services.notifications import Event

    alice = User(username="alice", password_hash="x")
    db.add(alice)
    db.flush()
    mine, theirs = _collection(db, "mine", added_by_id=alice.id), _collection(db, "theirs")
    _rule(db, "episode_downloaded", personal=True, user_id=alice.id, collection_scope="added")
    _device(db, alice.id)
    _emit(db, Event.EPISODE_DOWNLOADED, collection_id=theirs.id)
    assert not _deliveries(db)
    _emit(db, Event.EPISODE_DOWNLOADED, collection_id=mine.id)
    assert len(_deliveries(db)) == 1


def test_the_daily_summary_waits_for_its_time(db):
    from backend.services.notifications import Event
    from backend.services.notifications.delivery import next_summary_at

    _rule(db, "everything", delivery="daily", summary_time="08:00")
    _device(db)
    _emit(db, Event.UPDATE_AVAILABLE)
    (delivery,) = _deliveries(db)
    assert delivery.group_key.startswith("daily:")
    assert delivery.next_attempt_at.replace(tzinfo=timezone.utc) == next_summary_at("08:00", NOW)
    assert next_summary_at("08:00", NOW) > NOW


def _destination(db, kind, config, name="Somewhere"):
    from backend.services.notifications.destinations import Kind, create_destination

    return create_destination(db, kind=Kind(kind), name=name, config=config)


def test_media_server_refreshes_are_batched_into_one_call(db, monkeypatch):
    from backend.services.notifications import Event, delivery

    collection = _collection(db)
    jellyfin = _destination(db, "jellyfin", {"address": "http://jellyfin:8096/", "api_key": "secret"})
    _rule(db, "episode_downloaded", push=False, destination_ids=[jellyfin.id])
    for number in range(2):
        _emit(db, Event.EPISODE_DOWNLOADED, collection_id=collection.id,
              data={"folder": f"/downloads/Show/S{number}"})
    calls = []
    monkeypatch.setattr(
        "backend.services.notifications.senders.requests.request",
        lambda method, url, **kwargs: calls.append((method, url, kwargs)) or Mock(status_code=204),
    )
    assert delivery.deliver_pending(db, now=NOW + timedelta(minutes=2)) == 1
    ((method, url, kwargs),) = calls
    assert (method, url) == ("POST", "http://jellyfin:8096/Library/Media/Updated")
    assert kwargs["headers"] == {"X-Emby-Token": "secret"}
    assert [update["Path"] for update in kwargs["json"]["Updates"]] == ["/downloads/Show/S0", "/downloads/Show/S1"]
    assert {row.status for row in _deliveries(db)} == {"SENT"}


def test_a_failing_webhook_is_tried_again_then_reported(db, monkeypatch):
    from backend.db.models import NotificationEvent
    from backend.services.notifications import Event, delivery

    collection = _collection(db)
    hook = _destination(db, "webhook", {"url": "https://example.com/hook", "method": "POST"})
    _rule(db, "episode_downloaded", push=False, destination_ids=[hook.id])
    _emit(db, Event.EPISODE_DOWNLOADED, collection_id=collection.id, data={"collection": "Show", "episode": "One"})
    bodies = []
    monkeypatch.setattr(
        "backend.services.notifications.senders.requests.request",
        lambda method, url, **kwargs: bodies.append(json.loads(kwargs["data"])) or Mock(status_code=500),
    )
    at = NOW
    for _ in range(4):
        delivery.deliver_pending(db, now=at)
        at += timedelta(minutes=5)
    (row,) = [row for row in _deliveries(db) if row.destination_id == hook.id]
    assert (row.status, row.attempts, row.error) == ("FAILED", 4, "It answered with HTTP 500")
    assert bodies[0]["event"] == "episode_downloaded" and bodies[0]["collection"] == "Show"
    assert db.scalar(select(NotificationEvent).where(NotificationEvent.event == Event.TASK_FAILING.value)) is not None


def test_destination_settings_are_checked_and_stored_secretly(db, tmp_path, monkeypatch):
    from backend.services.notifications.apprise_services import InvalidDestination
    from backend.services.notifications.destinations import config_of

    with pytest.raises(InvalidDestination):
        _destination(db, "webhook", {"url": "ftp://example.com"})
    with pytest.raises(InvalidDestination):
        _destination(db, "plex", {"address": "http://plex:32400"})
    monkeypatch.setattr("backend.services.notifications.destinations.scripts_folder", lambda: tmp_path)
    outside = tmp_path.parent / "outside.sh"
    outside.write_text("#!/bin/sh\n")
    outside.chmod(0o755)
    with pytest.raises(InvalidDestination):
        _destination(db, "script", {"script": "../outside.sh"})
    plex = _destination(db, "plex", {"address": "http://plex:32400", "api_key": "token"})
    assert "token" not in plex.encrypted_config and plex.masked == "http://plex:32400"
    assert config_of(plex)["api_key"] == "token"


def test_a_script_gets_the_download_in_its_environment(db, tmp_path, monkeypatch):
    from backend.db.models import NotificationEvent
    from backend.services.notifications.senders import run_script

    monkeypatch.setattr("backend.services.notifications.destinations.scripts_folder", lambda: tmp_path)
    out = tmp_path / "out.txt"
    script = tmp_path / "tell.sh"
    script.write_text(f'#!/bin/sh\necho "$VODLOFT_EVENT|$VODLOFT_FOLDER" > {out}\n')
    script.chmod(0o755)
    event = NotificationEvent(event="episode_downloaded", title="t", body="", data={"folder": "/downloads/Show"})
    assert run_script({"script": "tell.sh", "timeout_seconds": 10}, event).delivered
    assert out.read_text().strip() == "episode_downloaded|/downloads/Show"


def test_rules_api_refuses_sentences_that_cannot_work(db):
    from backend.api.endpoints.notifications import service
    from backend.api.models.notifications import RuleInput
    from backend.services.users import UserError

    with pytest.raises(UserError) as added:
        service.add_rule(db, RuleInput(event="episode_downloaded", collection_scope="added", push=True))
    assert added.value.field == "collectionScope"
    with pytest.raises(UserError) as nowhere:
        service.add_rule(db, RuleInput(event="download_failed"))
    assert nowhere.value.field == "destinationIds"
    with pytest.raises(UserError) as private:
        service.add_rule(db, RuleInput(event="disk_almost_full", push=True), personal=True, user_id=None)
    assert private.value.field == "event"
    with pytest.raises(ValueError):
        RuleInput(event="everything", push=True)
    rule = service.add_rule(db, RuleInput(event="episode_downloaded", push=True, delivery="grouped"))
    assert (rule.personal, rule.delivery) == (False, "grouped")


def test_new_episodes_only_count_for_collections_that_download_nothing(db):
    from backend.db.models import Episode, NotificationEvent, Season
    from backend.services.notifications.emitters import new_episodes_found

    collection = _collection(db)
    season = Season(collection=collection, index=1, slug="s1", name="One")
    db.add(season)
    for number in range(3):
        db.add(Episode(
            source_key="ytdlp", uuid=f"e{number}", type="episode", collection=collection, season=season, index=number,
            episode_identifier=f"ep.{number}", slug=f"e{number}", title=f"E{number}", publish_status="published_final",
            sharing_url=f"https://www.youtube.com/watch?v=e{number}",
        ))
    db.flush()
    new_episodes_found(db, collection, 3)
    assert db.scalar(select(NotificationEvent)) is None
    new_episodes_found(db, collection, 1)
    assert db.scalar(select(NotificationEvent)).title == "1 new episode in Show"


def test_push_reaches_the_push_service(monkeypatch):
    """Apprise refuses a time to live over a minute, which failed every push before it was sent."""
    import base64
    import os
    from types import SimpleNamespace

    import requests
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from backend.services.notifications import push

    def encoded(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    client = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )
    subscription = {"endpoint": "https://web.push.apple.com/device", "keys": {"p256dh": encoded(client), "auth": encoded(os.urandom(16))}}
    sent = []
    monkeypatch.setattr(push, "decrypt_text", lambda _value: json.dumps(subscription))
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: sent.append(url) or SimpleNamespace(status_code=201, content=b"", text="", headers={}))

    result = push.send_push(ec.generate_private_key(ec.SECP256R1()), SimpleNamespace(encrypted_subscription="x"), {"title": "Test"})
    assert result == "SENT" and sent == ["https://web.push.apple.com/device"]


def _apple_push(monkeypatch, status: int, content: bytes = b""):
    """Send one push to a fake Apple endpoint; returns the result and the requests made."""
    import base64
    import os
    from types import SimpleNamespace

    import requests
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from backend.services.notifications import push

    def encoded(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    client = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )
    subscription = {"endpoint": "https://web.push.apple.com/device", "keys": {"p256dh": encoded(client), "auth": encoded(os.urandom(16))}}
    sent = []
    monkeypatch.setattr(push, "decrypt_text", lambda _value: json.dumps(subscription))
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: sent.append(kwargs["headers"]) or SimpleNamespace(
        status_code=status, content=content, text=content.decode(), headers={},
    ))
    result = push.send_push(ec.generate_private_key(ec.SECP256R1()), SimpleNamespace(encrypted_subscription="x"), {"title": "Test"})
    return result, sent


def test_push_signs_a_subject_apple_accepts(monkeypatch):
    """Apple's push service answers 403 BadJwtToken to a subject at a .local address."""
    import base64

    result, (headers,) = _apple_push(monkeypatch, 201)
    token = headers["Authorization"].split("t=")[1].split(",")[0]
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert result == "SENT"
    assert claims["sub"] == "https://github.com/samuelvisser/vodloft" and claims["aud"] == "https://web.push.apple.com"


def test_a_refused_push_shows_the_push_service_reason(monkeypatch):
    refused, _ = _apple_push(monkeypatch, 403, b'{"reason":"BadJwtToken"}')
    assert (refused.delivered, refused.error, refused.retry) == (False, "The push service answered 403 (BadJwtToken)", False)
    busy, _ = _apple_push(monkeypatch, 503)
    assert (busy.error, busy.retry) == ("The push service answered 503", True)


def test_a_crash_fails_at_once_and_a_retry_shows_when_it_is_tried_again(db, monkeypatch):
    """History must not show "Waiting" for a message that already failed."""
    from backend.api.endpoints.notifications.service import history
    from backend.services.notifications import Event, delivery
    from backend.services.notifications.senders import Outcome

    _rule(db, "download_failed")
    _device(db, name="Phone")
    _emit(db, Event.DOWNLOAD_FAILED, dedupe_key="one")
    monkeypatch.setattr(delivery, "vapid_key", lambda session: None)

    def broken(*_args):
        raise ValueError("misconfigured")

    monkeypatch.setattr(delivery, "send_push", broken)
    delivery.deliver_pending(db, now=NOW + timedelta(minutes=1))
    (row,) = history(db)
    assert (row.status, row.error, row.retry_at) == ("FAILED", "Sending failed (ValueError)", None)

    _emit(db, Event.DOWNLOAD_FAILED, dedupe_key="two")
    monkeypatch.setattr(delivery, "send_push", lambda *_args: Outcome(False, "The push service answered 503"))
    delivery.deliver_pending(db, now=NOW + timedelta(minutes=1))
    retried = history(db)[0]
    assert retried.status == "PENDING" and retried.error == "The push service answered 503"
    assert retried.retry_at is not None
