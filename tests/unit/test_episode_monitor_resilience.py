from __future__ import annotations

from datetime import datetime, timezone

import pytest
from conftest import use_database
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session


def _episode_record(slug: str):
    from sources.dailywire.api.records import DwEpisodeRecord
    return DwEpisodeRecord(
        dw_id=f"remote-{slug}", slug=slug, title="Live episode", description=None,
        duration=3600, episode_number="101.00", display_episode_number="101.00",
        background_image_path=None, sharing_url=f"https://example.test/{slug}",
        publish_status="LIVE", is_downloadable=False, available_for=[],
        thumbnail_landscape_path=None, thumbnail_portrait_path=None, thumbnail_square_path=None,
        published_date=datetime(2026, 9, 5, 12, tzinfo=timezone.utc), scheduled_date=None,
    )


def _monitor_fixture():
    from backend.db import Base
    from backend.db.models import Season, Collection
    from backend.types.episode_types import EpisodePublishStatus
    from backend.types.collection_types import EpisodeIdentifier, CollectionType
    from backend.db.models import Episode
    from backend.utils.helpers import generate_uuid
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    session = Session(engine)
    collection = Collection(
        source_key="dailywire",
        uuid="collection-uuid", slug="test-collection", title="Test Show", description=None,
        sharing_url="https://example.test/collection", membership_level="FREE",
        type=CollectionType.PODCAST.value, episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Test Host", author_slug="test-host",
    )
    season = Season(collection=collection, index=1, slug="season-1", name="One")
    session.add_all([collection, season])
    session.flush()
    record = _episode_record("live-episode")
    episode = Episode(
        source_key="dailywire", uuid=generate_uuid(), type="episode", collection=collection, season=season, index=2,
        episode_identifier="ep.101", source_number="101.00", slug=record.slug, source_slug=record.slug,
        title=record.title, duration=record.duration, publish_status=EpisodePublishStatus.LIVE.value,
        sharing_url=record.sharing_url, published_date=record.published_date,
    )
    session.add(episode)
    session.commit()
    return engine, session, collection, episode



def test_pending_monitor_marks_unreconciled_404_as_removed_from_its_source(monkeypatch):
    from sources.dailywire.api.dw_api.client import MiddlewareAPIError
    from task_manager.tasks.workers.monitor_pending_episode import service
    engine, session, collection, episode = _monitor_fixture()

    class FakeClient:
        def get_episode_details(self, slug, *, require_member_exclusive):
            raise MiddlewareAPIError("not found", status_code=404)

    monkeypatch.setattr(service, "MiddlewareClient", FakeClient)
    monkeypatch.setattr(service, "_try_reconcile_slug_after_404", lambda *args, **kwargs: False)
    result = service.run_monitor_pending_episode(session, episode_id=episode.id)
    assert result is None
    session.expire_all()
    stored = session.get(type(episode), episode.id)
    # It was live, so it waits a few hours before it goes, with its status and identifier as they were.
    assert stored.publish_status == "live"
    assert stored.removed_from_source is True
    assert stored.episode_identifier == "ep.101"
    session.close()
    engine.dispose()


def test_pending_monitor_still_raises_non_404_dailywire_errors(monkeypatch):
    from sources.dailywire.api.dw_api.client import MiddlewareAPIError
    from task_manager.tasks.workers.monitor_pending_episode import service
    engine, session, collection, episode = _monitor_fixture()

    class FakeClient:
        def get_episode_details(self, slug, *, require_member_exclusive):
            raise MiddlewareAPIError("HTTP error 503", status_code=503)

    monkeypatch.setattr(service, "MiddlewareClient", FakeClient)
    with pytest.raises(MiddlewareAPIError, match="503"):
        service.run_monitor_pending_episode(session, episode_id=episode.id)
    session.close()
    engine.dispose()
