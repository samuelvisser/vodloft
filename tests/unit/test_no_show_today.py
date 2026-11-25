from __future__ import annotations

from profile_filters import filter_rows, line

from datetime import datetime, timezone

import pytest
from conftest import use_database
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session


# ---------- detection ----------

def test_no_show_today_detection_uses_slug_only():
    from backend.utils.episode_slug import is_no_show_today_slug

    assert is_no_show_today_slug("matt-walsh-1809-no-show-today") is True
    assert is_no_show_today_slug("MATT-WALSH-1809-NO-SHOW-TODAY") is True
    assert is_no_show_today_slug("matt-walsh-1809") is False
    assert is_no_show_today_slug(None) is False


# ---------- shared fixtures ----------

def _make_collection(session, *, slug="test-collection"):
    from backend.db.models import Collection
    from backend.types.collection_types import EpisodeIdentifier, CollectionType

    collection = Collection(
        source_key="dailywire",
        uuid=f"{slug}-uuid",
        slug=slug,
        title="Test Show",
        description=None,
        sharing_url=f"https://example.test/{slug}",
        membership_level="FREE",
        type=CollectionType.PODCAST.value,
        episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Host",
        author_slug="host",
    )
    session.add(collection)
    session.flush()
    return collection


def _make_season(session, collection, *, index=1, slug="season-1", name="One"):
    from backend.db.models import Season

    season = Season(collection=collection, index=index, slug=slug, name=name)
    session.add(season)
    session.flush()
    return season


def _make_episode(
        session,
        collection,
        season,
        *,
        slug,
        ep_id,
        title,
        index,
        publish_status="published_final",
        published_at=None,
):
    from backend.db.models import Episode
    from backend.utils.helpers import generate_uuid

    published_at = published_at or datetime.now(timezone.utc)
    episode = Episode(
        source_key="dailywire",
        uuid=generate_uuid(),
        type="episode",
        collection=collection,
        season=season,
        index=index,
        episode_identifier=ep_id,
        slug=slug,
        title=title,
        duration=100.0,
        publish_status=publish_status,
        sharing_url=f"https://example.test/{slug}",
        published_date=published_at,
    )
    session.add(episode)
    session.flush()
    return episode


def _make_local_media_profile(session, *, slug="audio"):
    from backend.db.models import LocalMediaProfile

    profile = LocalMediaProfile(
        slug=slug,
        name=slug,
        output_template="/downloads/{{ collection }}/{{ episode }}.ext",
        preferred_format="format_audio_only",
    )
    session.add(profile)
    session.flush()
    return profile


@pytest.fixture
def db_session():
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


def _dw_episode_record(slug: str, title: str):
    from sources.dailywire.api.records import DwEpisodeRecord

    return DwEpisodeRecord(
        dw_id=f"remote-{slug}",
        slug=slug,
        title=title,
        description=None,
        duration=100,
        episode_number="1.00",
        display_episode_number="1",
        background_image_path=None,
        sharing_url=f"https://example.test/{slug}",
        publish_status="PUBLISHED",
        is_downloadable=True,
        available_for=[],
        thumbnail_landscape_path=None,
        thumbnail_portrait_path=None,
        thumbnail_square_path=None,
        published_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        scheduled_date=None,
    )


# ---------- no-show state normalization ----------

def test_title_alone_does_not_make_episode_no_show_today(db_session):
    from backend.utils.episode_slug import is_no_show_today_slug
    from task_manager.tasks.helpers.episodes.save import upsert_episode

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episode = upsert_episode(
        db_session,
        collection=collection,
        season=season,
        ep=_dw_episode_record("matt-walsh-1809", "The Matt Walsh Show - No Show Today"),
        index_value=1,
        ep_id="ep.1809",
    )

    assert is_no_show_today_slug(episode.slug) is False


def test_no_show_today_placeholder_is_not_added(db_session):
    from backend.db.models import Episode
    from task_manager.tasks.helpers.episodes.save import (
        resolve_dw_episodes,
        save_resolved_episodes_per_season_asc,
    )

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    record = _dw_episode_record("matt-walsh-1809-no-show-today", "Ordinary title")
    [resolved] = resolve_dw_episodes(
        episodes=[("ep.1809", record)],
        client=object(),
        require_member_exclusive=False,
    )

    assert resolved.status is None

    _, saved = save_resolved_episodes_per_season_asc(
        db_session,
        collection=collection,
        season=season,
        episodes=[resolved],
        start_index=1,
    )
    assert saved == []
    assert db_session.query(Episode).count() == 0


# ---------- profile eligibility remains generic ----------

def test_download_profile_excludes_processing_status(db_session):
    from backend.db.models.download_profile import DownloadProfile
    from backend.types.download_profile_types import EpIdType
    from backend.types.episode_types import EpisodePublishStatus
    from task_manager.tasks.workers.download_profile_worker._helpers import (
        get_download_profile_episodes,
    )

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    lmp = _make_local_media_profile(db_session)

    real_ep = _make_episode(
        db_session,
        collection,
        season,
        slug="ep-real",
        ep_id="ep.1",
        title="Real episode",
        index=1,
    )
    processing_ep = _make_episode(
        db_session,
        collection,
        season,
        slug="ep-processing",
        ep_id="aux.2",
        title="Processing episode",
        index=3,
        publish_status=EpisodePublishStatus.SOURCE_PROCESSING.value,
    )

    profile = DownloadProfile(
        collection=collection,
        local_media_profile=lmp,
        enable_profile=True,
        filters=filter_rows(line("only", "types", episode_types=[EpIdType.EP.value, EpIdType.AUX.value])),
        download_with_countdown=False,
        redownload_final=False,
        delete_older_episodes=False,
    )
    db_session.add(profile)
    db_session.commit()

    slugs = {episode.slug for episode in get_download_profile_episodes(db_session, profile)}
    assert real_ep.slug in slugs
    assert processing_ep.slug not in slugs
