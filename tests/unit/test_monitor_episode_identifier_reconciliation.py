from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from conftest import use_database


def test_monitor_reconciles_identifier_while_episode_stays_pending(monkeypatch):
    import backend.db.models  # noqa: F401
    from backend.db import Base
    from backend.db.models import Episode, Season, Collection
    from backend.types.episode_types import EpisodePublishStatus
    from backend.types.collection_types import EpisodeIdentifier, CollectionType
    from backend.utils.helpers import generate_uuid
    from sources.dailywire.api.records import DwEpisodeDetailRecord
    from task_manager.tasks.helpers.episodes import events as episode_events
    from task_manager.tasks.workers.monitor_pending_episode import service

    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    session = Session(engine)

    collection = Collection(
        source_key="dailywire",
        uuid="collection-uuid",
        slug="the-ben-shapiro-show",
        title="The Ben Shapiro Show",
        description=None,
        sharing_url="https://example.test/collection",
        membership_level="FREE",
        type=CollectionType.PODCAST.value,
        episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Ben Shapiro",
        author_slug="ben-shapiro",
    )
    season = Season(collection=collection, index=1, slug="2026", name="2026", season_type="normal", season_number=1)
    session.add_all([collection, season])
    session.flush()

    old_identifier = "ep-extra.other.2500.1"
    episode = Episode(
        source_key="dailywire",
        uuid=generate_uuid(),
        type="episode",
        collection=collection,
        season=season,
        index=2500,
        episode_identifier=old_identifier,
        slug="the-ben-shapiro-show-2500",
        title="BREAKING: Judge Threatens Mistrial",
        duration=3600,
        publish_status=EpisodePublishStatus.LIVE.value,
        metadata_is_final=False,
        sharing_url="https://example.test/episode",
        published_date=datetime.now(timezone.utc),
    )
    session.add(episode)
    session.commit()

    published_at = datetime.now(timezone.utc)
    detail = DwEpisodeDetailRecord(
        dw_id="remote-2500",
        slug=episode.slug,
        title=episode.title,
        description=None,
        duration=3600,
        episode_number="2500.00",
        display_episode_number="2500",
        background_image_path=None,
        sharing_url=episode.sharing_url,
        publish_status="LIVE",
        is_downloadable=False,
        available_for=[],
        thumbnail_landscape_path=None,
        thumbnail_portrait_path=None,
        thumbnail_square_path=None,
        published_date=published_at,
        scheduled_date=None,
        audio_url="https://example.test/audio.mp3",
        video_url="https://example.test/video.m3u8",
        delivery_mode="VOD",
        progress=0,
        next_episode_url=None,
        playback_status=None,
    )

    class FakeClient:
        def get_episode_details(self, slug, *, require_member_exclusive):
            assert slug == episode.slug
            assert require_member_exclusive is False
            return detail

    monkeypatch.setattr(service, "MiddlewareClient", FakeClient)
    monkeypatch.setattr(episode_events, "queue_event", Mock())

    result = service.run_monitor_pending_episode(session, episode_id=episode.id)

    assert result is EpisodePublishStatus.LIVE
    session.expire_all()
    stored = session.get(Episode, episode.id)
    assert stored is not None
    assert stored.episode_identifier == "ep.2500"
    assert stored.dw_episode_number == "2500.00"

    session.close()
    engine.dispose()
