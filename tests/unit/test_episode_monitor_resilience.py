from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
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
    from task_manager.tasks.helpers.episodes.save import upsert_episode
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
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
    episode = upsert_episode(
        session, collection=collection, season=season,
        ep=_episode_record("live-episode").model_copy(update={"publish_status": EpisodePublishStatus.LIVE.value}, deep=True),
        index_value=2, ep_id="ep.101",
    )
    session.commit()
    return engine, session, collection, episode



def test_upsert_existing_episode_stores_raw_source_number_separately():
    from task_manager.tasks.helpers.episodes.save import upsert_episode

    engine, session, collection, episode = _monitor_fixture()
    record = _episode_record(episode.slug).model_copy(
        update={"episode_number": "101.10", "title": "Updated episode"},
        deep=True,
    )

    updated = upsert_episode(
        session,
        collection=collection,
        season=episode.season,
        ep=record,
        index_value=episode.index,
        ep_id="ep-extra.other.101.10",
    )

    assert updated.id == episode.id
    assert updated.dw_episode_number == "101.10"
    assert updated.episode_number == "101"
    assert updated.episode_sub_number == "10"
    assert updated.title == "Updated episode"
    session.close()
    engine.dispose()

def test_pending_monitor_marks_unreconciled_404_as_no_usable_media(monkeypatch):
    from backend.types.episode_types import EpisodePublishStatus
    from sources.dailywire.api.dw_api.client import MiddlewareAPIError
    from task_manager.tasks.helpers.episodes.unusable_media import NoUsableMediaReason, episode_no_usable_media_reason, episode_no_usable_media_since
    from task_manager.tasks.workers.monitor_pending_episode import service
    engine, session, collection, episode = _monitor_fixture()

    class FakeClient:
        def get_episode_details(self, slug, *, require_member_exclusive):
            raise MiddlewareAPIError("not found", status_code=404)

    monkeypatch.setattr(service, "MiddlewareClient", FakeClient)
    monkeypatch.setattr(service, "_try_reconcile_slug_after_404", lambda *args, **kwargs: False)
    result = service.run_monitor_pending_episode(session, episode_id=episode.id)
    assert result is EpisodePublishStatus.NO_USABLE_MEDIA
    session.expire_all()
    stored = session.get(type(episode), episode.id)
    assert stored.publish_status == EpisodePublishStatus.NO_USABLE_MEDIA.value
    assert stored.episode_identifier == "not-usable.1"
    assert stored.get_meta("no_usable_media.previous_identifier") == "ep.101"
    assert episode_no_usable_media_reason(stored) is NoUsableMediaReason.NOT_FOUND
    assert episode_no_usable_media_since(stored) is not None
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
