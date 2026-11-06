from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


def test_metadata_refresh_interval_parser_normalizes_and_validates():
    from config.settings.submodels import (
        normalize_metadata_refresh_intervals,
        parse_metadata_refresh_intervals,
    )

    value = "5m, 15m,30m,1h,3h,6h,24h"
    assert normalize_metadata_refresh_intervals(value) == "5m,15m,30m,1h,3h,6h,24h"
    assert parse_metadata_refresh_intervals(value) == (
        300,
        900,
        1800,
        3600,
        10800,
        21600,
        86400,
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        parse_metadata_refresh_intervals("5m,1h,30m")
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_metadata_refresh_intervals("60m,1h")
    with pytest.raises(ValueError, match="positive"):
        parse_metadata_refresh_intervals("5m,soon")


def test_app_settings_exposes_default_metadata_refresh_intervals():
    from config.settings.settings import AppSettings

    assert (
        AppSettings().new_episode_schedule.metadata_refresh_intervals
        == "1h,6h,24h,3d"
    )


def test_new_episode_metadata_finality_uses_last_interval(monkeypatch):
    from backend.types.episode_types import EpisodePublishStatus
    from task_manager.tasks.helpers.episodes import metadata

    offsets = (300, 900, 1800, 3600, 10800, 21600, 86400)
    now = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)

    assert metadata.metadata_is_final_for_new_episode(
        EpisodePublishStatus.LIVE,
        now - timedelta(days=2),
        offsets,
        now=now,
    ) is False
    assert metadata.metadata_is_final_for_new_episode(
        EpisodePublishStatus.PUBLISHED_FINAL,
        now - timedelta(hours=23),
        offsets,
        now=now,
    ) is False
    assert metadata.metadata_is_final_for_new_episode(
        EpisodePublishStatus.PUBLISHED_FINAL,
        now - timedelta(hours=25),
        offsets,
        now=now,
    ) is True


@pytest.mark.parametrize("has_safe_final", [True, False])
def test_the_refresh_schedule_counts_from_the_safe_final_publication(has_safe_final):
    from backend.types.episode_types import EpisodePublishStatus
    from task_manager.tasks.workers.refresh_metadata.service import _watched_episode

    dailywire_published = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
    safe_final = datetime(2026, 10, 2, 9, 3, tzinfo=timezone.utc)
    episode = SimpleNamespace(
        id=42, source_key="dailywire", source_slug="episode", sharing_url="https://example.test/episode",
        metadata_is_final=False, publish_status=EpisodePublishStatus.PUBLISHED_FINAL.value,
        safe_published_final=safe_final if has_safe_final else None, last_known_pending=None,
        published_date=dailywire_published, collection=SimpleNamespace(site=None),
    )

    item = _watched_episode(episode)

    assert item.published == (safe_final if has_safe_final else dailywire_published)
    # The Daily Wire's own refresh looks it up.
    assert item.one_by_one


def test_the_refresh_schedule_ignores_the_ensure_safe_delay_setting(monkeypatch):
    from backend.types.episode_types import EpisodePublishStatus
    from config import get_settings
    from task_manager.tasks.workers.refresh_metadata.service import _watched_episode

    monkeypatch.setattr(get_settings().download_settings, "ensure_safe_delay", True)
    last_known_pending = datetime(2026, 10, 2, 9, tzinfo=timezone.utc)
    episode = SimpleNamespace(
        id=42, source_key="dailywire", source_slug="episode", sharing_url="https://example.test/episode",
        metadata_is_final=False, publish_status=EpisodePublishStatus.PUBLISHED_FINAL.value,
        safe_published_final=None, last_known_pending=last_known_pending,
        published_date=datetime(2026, 10, 2, 8, tzinfo=timezone.utc), collection=SimpleNamespace(site=None),
    )

    assert _watched_episode(episode).published == last_known_pending


def test_refresh_now_runs_only_when_asked():
    import inspect
    import task_manager.tasks  # noqa: F401
    from task_manager.scheduler.registry import get_task

    meta, worker = get_task("refresh_episode_metadata")

    # The metadata refresh sweep follows episodes; this task only answers Refresh now.
    assert not meta.triggers
    assert list(inspect.signature(worker).parameters) == ["resource_id", "progress"]


def test_episode_metadata_refresh_creates_operation_and_queues_worker(monkeypatch):
    from backend.api.endpoints.episodes import service

    episode = SimpleNamespace(
        id=17,
        source_key="dailywire",
        slug="test-episode",
        title="Test Episode",
        collection_id=3,
        metadata_is_final=True,
        collection=SimpleNamespace(slug="test-collection", title="Test Show"),
    )
    queued: list[tuple[str, str]] = []
    created: list[dict] = []

    class Query:
        def filter_by(self, **kwargs):
            assert kwargs == {"slug": episode.slug}
            return self

        def one_or_none(self):
            return episode

    class FakeSession:
        def __init__(self):
            self.flushes = 0

        def query(self, model):
            return Query()

        def flush(self):
            self.flushes += 1

    def fake_create_operation(_session, **kwargs):
        created.append(kwargs)
        return SimpleNamespace(id="operation-episode-refresh")

    def fake_dispatch(_session, operation_id, slot_key):
        queued.append((operation_id, slot_key))
        return True

    session = FakeSession()
    monkeypatch.setattr(service, "create_operation", fake_create_operation)
    monkeypatch.setattr(service, "queue_operation_target_dispatch", fake_dispatch)

    result = service.request_episode_metadata_refresh(session, episode.slug)

    assert result == {
        "queued": True,
        "episode_id": episode.id,
        "operation_id": "operation-episode-refresh",
    }
    assert episode.metadata_is_final is False
    assert session.flushes == 1
    assert created[0]["kind"] == "episode.refresh_metadata"
    assert created[0]["resource_id"] == episode.id
    target = created[0]["targets"][0]
    assert target.task_key == "refresh_episode_metadata"
    assert target.task_kwargs == {}
    assert queued == [("operation-episode-refresh", target.resolved_slot_key())]


def test_collection_metadata_refresh_creates_one_operation_for_all_episode_targets(monkeypatch):
    from backend.api.endpoints.collections import service
    from backend.db.models import Episode, Collection

    collection = SimpleNamespace(id=9, source_key="dailywire", slug="test-collection", title="Test Show")
    episodes = [
        SimpleNamespace(id=1, metadata_is_final=True),
        SimpleNamespace(id=2, metadata_is_final=True),
        SimpleNamespace(id=3, metadata_is_final=False),
    ]
    queued: list[tuple[str, str]] = []
    created: list[dict] = []

    class Query:
        def __init__(self, model):
            self.model = model

        def filter_by(self, **kwargs):
            if self.model is Collection:
                assert kwargs == {"slug": collection.slug}
            elif self.model is Episode:
                assert kwargs == {"collection_id": collection.id}
            return self

        def one_or_none(self):
            assert self.model is Collection
            return collection

        def all(self):
            assert self.model is Episode
            return episodes

    class FakeSession:
        def __init__(self):
            self.flushes = 0

        def query(self, model):
            return Query(model)

        def flush(self):
            self.flushes += 1

    def fake_create_operation(_session, definition):
        created.append({"kind": definition.kind, "targets": definition.targets()})
        return SimpleNamespace(id="operation-collection-refresh")

    def fake_dispatch(_session, operation_id, slot_key):
        queued.append((operation_id, slot_key))
        return True

    session = FakeSession()
    monkeypatch.setattr(service, "create_operation", fake_create_operation)
    monkeypatch.setattr(service, "queue_operation_target_dispatch", fake_dispatch)

    result = service.request_collection_metadata_refresh(session, collection.slug)

    assert result == {
        "queued": True,
        "episodes_queued": 3,
        "operation_id": "operation-collection-refresh",
    }
    assert created[0]["kind"] == "collection.refresh_metadata"
    assert [target.resource_id for target in created[0]["targets"]] == [1, 2, 3]
    assert all(target.task_key == "refresh_episode_metadata" for target in created[0]["targets"])
    assert all(target.task_kwargs == {} for target in created[0]["targets"])
    assert queued == [
        ("operation-collection-refresh", "episode:1"),
        ("operation-collection-refresh", "episode:2"),
        ("operation-collection-refresh", "episode:3"),
    ]
    assert all(episode.metadata_is_final is False for episode in episodes)
    assert session.flushes == 1


def test_refresh_now_leaves_an_episode_that_is_not_published_alone(monkeypatch):
    from backend.types.episode_types import EpisodePublishStatus
    from task_manager.tasks.workers.refresh_metadata import service

    episode = SimpleNamespace(id=21, source_key="dailywire", metadata_is_final=False, publish_status=EpisodePublishStatus.LIVE.value)

    class FakeSession:
        def get(self, model, episode_id):
            assert episode_id == episode.id
            return episode

        def rollback(self):
            pass

    monkeypatch.setattr(service, "refresh_dailywire_episode", lambda *_args: pytest.fail("looked up"))

    assert service.refresh_episode_now(FakeSession(), episode.id).summary() == "No metadata refresh is due"
