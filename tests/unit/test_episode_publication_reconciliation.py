from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from conftest import use_database


def _episode_record(
        slug: str,
        *,
        title: str = "Episode 2500",
        episode_number: str = "2500.00",
        publish_status: str = "PUBLISHED",
        published_at: datetime | None = None,
        downloadable: bool = True,
        duration: float = 3600,
):
    from sources.dailywire.api.records import DwEpisodeRecord
    return DwEpisodeRecord(
        dw_id=f"remote-{slug}", slug=slug, title=title, description=None,
        duration=duration, episode_number=episode_number, display_episode_number=episode_number,
        background_image_path=None, sharing_url=f"https://example.test/{slug}",
        publish_status=publish_status, is_downloadable=downloadable, available_for=[],
        thumbnail_landscape_path=None, thumbnail_portrait_path=None, thumbnail_square_path=None,
        published_date=published_at or datetime.now(timezone.utc), scheduled_date=None,
    )


def _episode_detail(**kwargs):
    from sources.dailywire.api.records import DwEpisodeDetailRecord
    record = _episode_record(**kwargs)
    return DwEpisodeDetailRecord(
        **record.model_dump(mode="python", by_alias=False),
        audio_url="https://example.test/audio.mp3",
        video_url="https://example.test/video.m3u8",
        delivery_mode="VOD", progress=0, next_episode_url=None, playback_status=None,
    )


def _timing_settings():
    return SimpleNamespace(
        episode_status_timing=SimpleNamespace(
            published_final_after_minutes=180,
            dw_processing_max_minutes=60,
        )
    )


def test_final_timeout_never_overrides_authoritative_live(monkeypatch):
    from backend.types.episode_types import EpisodePublishStatus
    from task_manager.tasks.helpers.episodes import status
    monkeypatch.setattr(status, "get_settings", _timing_settings)
    detail = _episode_detail(
        slug="still-marked-live",
        publish_status="LIVE",
        published_at=datetime.now(timezone.utc) - timedelta(minutes=181),
        downloadable=False,
    )
    assert status.get_publish_status_from_dw_detail(detail) is EpisodePublishStatus.LIVE
    assert status.is_published_final(detail) is False


def test_no_show_today_is_inferred_from_slug_not_title(monkeypatch):
    from backend.types.episode_types import EpisodePublishStatus
    from task_manager.tasks.helpers.episodes import status
    monkeypatch.setattr(status, "get_settings", _timing_settings)
    monkeypatch.setattr(status, "get_vod_info", lambda _url: SimpleNamespace(seconds=3600))
    detail = _episode_detail(
        slug="the-ben-shapiro-show-no-show-today",
        title="A completely ordinary title",
        published_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    assert status.get_publish_status_from_dw_detail(detail) is None
    assert status.is_published_final(detail) is False


def test_countdown_timeout_only_advances_current_countdown_snapshot(monkeypatch):
    from backend.types.episode_types import EpisodePublishStatus
    from task_manager.tasks.helpers.episodes import status
    monkeypatch.setattr(status, "get_settings", _timing_settings)
    monkeypatch.setattr(status, "get_vod_info", lambda _url: SimpleNamespace(seconds=3600))
    detail = _episode_detail(
        slug="episode-2500",
        published_at=datetime.now(timezone.utc) - timedelta(minutes=181),
        downloadable=False,
    )
    observed = status.observe_episode_detail(detail)
    assert observed.status is EpisodePublishStatus.PUBLISHED_PRELIMINARY
    assert status.resolve_episode_status(
        detail,
        publication_timing_reference=detail.published_date,
        snapshot=observed,
    ).status is EpisodePublishStatus.PUBLISHED_FINAL


def test_countdown_timeout_can_use_explicit_safe_live_reference(monkeypatch):
    from backend.types.episode_types import EpisodePublishStatus
    from task_manager.tasks.helpers.episodes import status

    monkeypatch.setattr(status, "get_settings", _timing_settings)
    monkeypatch.setattr(status, "get_vod_info", lambda _url: SimpleNamespace(seconds=3600))
    now = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
    detail = _episode_detail(
        slug="episode-safe-live-clock",
        published_at=now - timedelta(hours=4),
        downloadable=False,
    )
    observed = status.observe_episode_detail(detail)
    assert observed.status is EpisodePublishStatus.PUBLISHED_PRELIMINARY

    # The Daily Wire timestamp alone would trip the 180-minute fallback. A
    # trusted live-end observation explicitly selected by the caller must not.
    resolved = status.resolve_episode_status(
        detail,
        publication_timing_reference=now - timedelta(minutes=10),
        now=now,
        snapshot=observed,
    )
    assert resolved.status is EpisodePublishStatus.PUBLISHED_PRELIMINARY


def test_dw_processing_uses_short_metadata_long_hls_and_times_out(monkeypatch):
    from backend.types.episode_types import EpisodePublishStatus
    from task_manager.tasks.helpers.episodes import status
    monkeypatch.setattr(status, "get_settings", _timing_settings)
    monkeypatch.setattr(status, "get_vod_info", lambda _url: SimpleNamespace(seconds=120))
    recent = _episode_detail(
        slug="episode-processing",
        duration=11.8,
        published_at=datetime.now(timezone.utc) - timedelta(minutes=59),
    )
    stale = _episode_detail(
        slug="episode-processing",
        duration=11.8,
        published_at=datetime.now(timezone.utc) - timedelta(minutes=61),
    )
    assert status.observe_episode_detail(recent).status is EpisodePublishStatus.SOURCE_PROCESSING
    assert status.resolve_episode_status(
        recent,
        publication_timing_reference=recent.published_date,
    ).status is EpisodePublishStatus.SOURCE_PROCESSING
    assert status.resolve_episode_status(
        stale,
        publication_timing_reference=stale.published_date,
    ).status is None


def test_transition_policy_reuses_the_single_hls_observation(monkeypatch):
    from backend.types.episode_types import EpisodePublishStatus
    from task_manager.tasks.helpers.episodes import status
    monkeypatch.setattr(status, "get_settings", _timing_settings)
    get_vod_info = Mock(return_value=SimpleNamespace(seconds=120))
    monkeypatch.setattr(status, "get_vod_info", get_vod_info)
    detail = _episode_detail(
        slug="episode-processing",
        duration=11.8,
        published_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )

    observed = status.observe_episode_detail(detail)
    resolved = status.resolve_episode_status(
        detail,
        publication_timing_reference=detail.published_date,
        snapshot=observed,
    )

    assert resolved.status is EpisodePublishStatus.SOURCE_PROCESSING
    get_vod_info.assert_called_once_with(detail.video_url)


def test_incremental_detail_404_overrides_age_fallback(monkeypatch):
    from backend.types.episode_types import EpisodePublishStatus
    from sources.dailywire.api.dw_api.client import MiddlewareAPIError
    from task_manager.tasks.helpers.episodes import save, status
    monkeypatch.setattr(status, "get_settings", _timing_settings)
    record = _episode_record("missing-detail", published_at=datetime.now(timezone.utc) - timedelta(hours=10))

    class FakeClient:
        def get_episode_details(self, slug, *, require_member_exclusive):
            raise MiddlewareAPIError("HTTP error 404: episode not found", status_code=404)

    [resolved] = save.resolve_dw_episodes(
        episodes=[("ep.2500", record)], client=FakeClient(),
        require_member_exclusive=False, always_resolve_details=True,
    )
    assert resolved.status is None
    assert resolved.detail_resolved is True


def test_initial_back_catalog_can_shortcut_old_final_without_detail(monkeypatch):
    from backend.types.episode_types import EpisodePublishStatus
    from task_manager.tasks.helpers.episodes import save, status
    monkeypatch.setattr(status, "get_settings", _timing_settings)
    record = _episode_record("old-back-catalog", published_at=datetime.now(timezone.utc) - timedelta(days=100))
    client = Mock()
    [resolved] = save.resolve_dw_episodes(
        episodes=[("ep.1", record)], client=client, require_member_exclusive=False,
    )
    assert resolved.status is EpisodePublishStatus.PUBLISHED_FINAL
    assert resolved.detail_resolved is False
    client.get_episode_details.assert_not_called()


def _make_collection_and_episode(session, *, identifier: str):
    from backend.db.models import Episode, Season, Collection
    from backend.types.collection_types import EpisodeIdentifier, CollectionType
    from backend.utils.helpers import generate_uuid
    collection = Collection(
        source_key="dailywire",
        uuid="collection-uuid", slug="the-ben-shapiro-show", title="The Ben Shapiro Show",
        description=None, sharing_url="https://example.test/collection", membership_level="FREE",
        type=CollectionType.PODCAST.value, episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Ben Shapiro", author_slug="ben-shapiro",
    )
    season = Season(
        collection=collection,
        index=1,
        slug="2026",
        name="2026",
        season_type="normal",
        season_number=1,
    )
    session.add_all([collection, season])
    session.flush()
    episode = Episode(
        source_key="dailywire",
        uuid=generate_uuid(), type="episode", collection=collection, season=season, index=2500,
        episode_identifier=identifier, slug="the-ben-shapiro-show-2500",
        title="BREAKING: Judge Threatens Mistrial", duration=2500,
        publish_status="published_final", metadata_is_final=False,
        sharing_url="https://example.test/episode",
        published_date=datetime.now(timezone.utc),
    )
    session.add(episode)
    session.commit()
    return collection, episode


def test_metadata_refresh_repairs_wrong_main_episode_identifier(monkeypatch):
    import backend.db.models  # noqa: F401
    from backend.db import Base
    from task_manager.tasks.workers.refresh_episode_metadata import service
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    session = Session(engine)
    collection, episode = _make_collection_and_episode(session, identifier="ep-extra.other.2500.1")
    detail = _episode_detail(slug=episode.slug, episode_number="2500.00", publish_status="PUBLISHED")

    class FakeClient:
        def get_episode_details(self, slug, *, require_member_exclusive):
            assert slug == episode.slug
            return detail

    from task_manager.tasks.helpers.episodes import status

    monkeypatch.setattr(service, "MiddlewareClient", FakeClient)
    monkeypatch.setattr(status, "get_vod_info", lambda _url: SimpleNamespace(seconds=3600))
    assert service.refresh_dailywire_episode(session, episode.id) is True
    session.expire_all()
    stored = session.get(type(episode), episode.id)
    assert stored.episode_identifier == "ep.2500"
    assert stored.dw_episode_number == "2500.00"
    session.close()
    engine.dispose()


def test_identifier_reconciliation_can_fix_extra_ordinal_after_collision_is_gone():
    import backend.db.models  # noqa: F401
    from backend.db import Base
    from task_manager.tasks.helpers.episodes.identifier import refresh_episode_identifier
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    session = Session(engine)
    collection, episode = _make_collection_and_episode(session, identifier="ep-extra.other.2500.2")
    detail = _episode_detail(slug=episode.slug, episode_number="2500.01")
    assert refresh_episode_identifier(session, episode, detail) is True
    session.commit()
    assert episode.episode_identifier == "ep-extra.other.2500.1"
    session.close()
    engine.dispose()


def test_identifier_reconciliation_uses_dailywire_segment_10_directly():
    import backend.db.models  # noqa: F401
    from backend.db import Base
    from task_manager.tasks.helpers.episodes.identifier import refresh_episode_identifier
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    session = Session(engine)
    _collection, episode = _make_collection_and_episode(session, identifier="ep-extra.other.2500.1")
    detail = _episode_detail(slug=episode.slug, episode_number="2500.10")
    assert refresh_episode_identifier(session, episode, detail) is True
    assert episode.episode_identifier == "ep-extra.other.2500.10"
    session.close()
    engine.dispose()


def test_dw_processing_safeguard_defaults_to_an_hour():
    from config.settings.settings import AppSettings
    settings = AppSettings(timezone="UTC")
    assert settings.episode_status_timing.dw_processing_max_minutes == 60
