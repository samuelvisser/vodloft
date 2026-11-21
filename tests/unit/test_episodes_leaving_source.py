"""An episode its Source no longer has goes when it has no files, and stays, marked removed, when it has.
One that went live and is not published yet waits four hours first."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import available_artifact, use_database
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 11, 18, 10, tzinfo=timezone.utc)


@pytest.fixture
def session():
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


def _episode(session, status="published_final", *, files=False, url="https://example.test/show"):
    from backend.db.models import Collection, Episode, EpisodeMediaDownload, LocalMediaProfile, Season
    from backend.types.collection_types import CollectionType, EpisodeIdentifier

    collection = Collection(
        source_key="ytdlp", uuid="c-uuid", slug="show", title="Show", sharing_url=url,
        membership_level="FREE", type=CollectionType.PODCAST.value, episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Host", author_slug="host",
    )
    season = Season(collection=collection, index=1, slug="s1", name="One")
    episode = Episode(
        source_key="ytdlp", uuid="e-uuid", type="episode", collection=collection, season=season, index=1,
        episode_identifier="ep.1", slug="e1", title="Episode", duration=100.0, publish_status=status,
        sharing_url="https://example.test/e1", published_date=NOW - timedelta(days=1),
    )
    session.add(episode)
    session.flush()
    if files:
        profile = LocalMediaProfile(slug="video", name="video", output_template="/d/{{ episode }}.ext", preferred_format="format_1080p")
        session.add(profile)
        session.flush()
        session.add(EpisodeMediaDownload(
            type="episode", media_item_id=episode.id, local_media_profile_id=profile.id, file_path="/d/e1.mp4",
            **available_artifact(),
        ))
    session.commit()
    return episode.id


def _left(session, episode_id, now=NOW):
    from backend.db.models import Episode
    from backend.services.removed_downloads import left_source

    deleted = left_source(session, session.get(Episode, episode_id), now=now)
    session.commit()
    return deleted


def test_an_episode_without_files_goes(session):
    from backend.db.models import Episode

    episode_id = _episode(session)

    assert _left(session, episode_id) is True
    assert session.get(Episode, episode_id) is None


def test_an_upcoming_stream_that_is_cancelled_goes_at_once(session):
    from backend.db.models import Episode

    episode_id = _episode(session, "scheduled")

    assert _left(session, episode_id) is True
    assert session.get(Episode, episode_id) is None


def test_a_downloaded_episode_stays_marked_removed_and_home_asks_about_it(session):
    from backend.db.models import Episode
    from backend.services.removed_downloads import downloads_awaiting_keep_answer

    episode_id = _episode(session, files=True)

    assert _left(session, episode_id) is False
    episode = session.get(Episode, episode_id)
    assert episode.removed_from_source is True
    assert episode.publish_status == "published_final"
    assert [download.media_item_id for download in downloads_awaiting_keep_answer(session)] == [episode_id]


def test_a_downloaded_video_its_sites_retention_removed_is_not_asked_about(session):
    from backend.api.models.episode import EpisodeAPIRead
    from backend.db.models import Episode
    from backend.services.removed_downloads import back_at_source, downloads_awaiting_keep_answer

    episode_id = _episode(session, files=True, url="https://www.twitch.tv/spamfish/videos?filter=all")

    assert _left(session, episode_id) is False
    episode = session.get(Episode, episode_id)
    assert episode.removed_from_source and episode.removed_by_retention
    # Twitch deletes its past broadcasts itself, so Home does not ask whether to keep the download.
    assert downloads_awaiting_keep_answer(session) == []
    assert back_at_source(episode) and not episode.removed_by_retention


@pytest.mark.parametrize("status", ["live", "source_processing", "published_preliminary"])
def test_an_episode_that_went_live_waits_four_hours_before_it_goes(session, status):
    from backend.db.models import Episode

    episode_id = _episode(session, status)

    assert _left(session, episode_id) is False
    assert session.get(Episode, episode_id).removed_from_source is True
    assert _left(session, episode_id, NOW + timedelta(hours=3, minutes=59)) is False
    assert _left(session, episode_id, NOW + timedelta(hours=4)) is True
    assert session.get(Episode, episode_id) is None


def test_an_episode_that_comes_back_starts_a_new_wait(session):
    from backend.db.models import Episode
    from backend.services.removed_downloads import back_at_source

    episode_id = _episode(session, "live")
    _left(session, episode_id)

    assert back_at_source(session.get(Episode, episode_id)) is True
    session.commit()
    episode = session.get(Episode, episode_id)
    assert episode.removed_from_source is False
    assert episode.get_meta("removed_from_source.since") is None
    assert _left(session, episode_id, NOW + timedelta(hours=5)) is False
