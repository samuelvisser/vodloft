from __future__ import annotations

from profile_filters import filter_rows, latest, line

from conftest import available_artifact
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _make_collection(session):
    from backend.db.models import Collection
    from backend.types.collection_types import EpisodeIdentifier, CollectionType

    collection = Collection(
        source_key="dailywire",
        uuid="episode-limit-collection-uuid",
        slug="episode-limit-collection",
        title="Episode Limit Show",
        description=None,
        sharing_url="https://example.test/episode-limit-collection",
        membership_level="FREE",
        type=CollectionType.PODCAST.value,
        episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Host",
        author_slug="host",
    )
    session.add(collection)
    session.flush()
    return collection


def _make_season(session, collection):
    from backend.db.models import Season

    season = Season(collection=collection, index=1, slug="season-1", name="One")
    session.add(season)
    session.flush()
    return season


def _make_episode(session, collection, season, *, index: int, published_at: datetime):
    from backend.db.models import Episode
    from backend.utils.helpers import generate_uuid

    episode = Episode(
        source_key="dailywire",
        uuid=generate_uuid(),
        type="episode",
        collection=collection,
        season=season,
        index=index,
        episode_identifier=f"ep.{index}",
        slug=f"episode-{index}",
        title=f"Episode {index}",
        duration=100.0,
        publish_status="published_final",
        sharing_url=f"https://example.test/episode-{index}",
        published_date=published_at,
    )
    session.add(episode)
    session.flush()
    return episode


def _make_local_media_profile(session):
    from backend.db.models import LocalMediaProfile

    profile = LocalMediaProfile(
        slug="episode-limit-audio",
        name="Episode limit audio",
        output_template="/downloads/{{ collection }}/{{ episode }}.ext",
        preferred_format="format_audio_only",
    )
    session.add(profile)
    session.flush()
    return profile


def _make_podcast_profile(session, collection, local_media_profile, *, count: int, delete_older: bool = False):
    from backend.db.models.download_profile import DownloadProfile
    from backend.types.download_profile_types import EpIdType

    profile = DownloadProfile(
        collection=collection,
        local_media_profile=local_media_profile,
        enable_profile=True,
        filters=filter_rows(line("only", "types", episode_types=[EpIdType.EP.value]), latest(count)),
        download_with_countdown=False,
        redownload_final=False,
        delete_older_episodes=delete_older,
    )
    session.add(profile)
    session.flush()
    return profile


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    import backend.db.models  # noqa: F401
    from backend.db import Base
    from config import get_settings

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    yield session
    session.close()
    engine.dispose()


def test_podcast_profile_selects_only_latest_episode_count(db_session):
    from task_manager.tasks.workers.download_profile_worker._helpers import get_download_profile_episodes

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    local_media_profile = _make_local_media_profile(db_session)
    now = datetime.now(timezone.utc)
    episodes = [
        _make_episode(db_session, collection, season, index=index, published_at=now - timedelta(days=4 - index))
        for index in range(1, 5)
    ]
    profile = _make_podcast_profile(db_session, collection, local_media_profile, count=2)

    selected = get_download_profile_episodes(db_session, profile)
    assert [episode.id for episode in selected] == [episodes[3].id, episodes[2].id]


def test_episode_scoped_run_still_checks_global_latest_set(db_session):
    from task_manager.tasks.workers.download_profile_worker._helpers import get_download_profile_episodes

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    local_media_profile = _make_local_media_profile(db_session)
    now = datetime.now(timezone.utc)
    old_episode = _make_episode(db_session, collection, season, index=1, published_at=now - timedelta(days=10))
    newest_episode = _make_episode(db_session, collection, season, index=2, published_at=now)
    profile = _make_podcast_profile(db_session, collection, local_media_profile, count=1)

    assert get_download_profile_episodes(db_session, profile, only_episode=old_episode) == []
    assert get_download_profile_episodes(db_session, profile, only_episode=newest_episode) == [newest_episode]


def test_episode_count_cleanup_removes_available_and_absent_artifacts_outside_limit(db_session, tmp_path):
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.types.download_profile_types import MediaDownloadArtifactStatus
    from backend.types.media_types import MediaType
    from backend.services.collections import remove_downloaded_files
    from task_manager.tasks.workers.download_profile_worker._helpers import cleanup_older_episodes

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    local_media_profile = _make_local_media_profile(db_session)
    now = datetime.now(timezone.utc)
    episodes = [
        _make_episode(db_session, collection, season, index=index, published_at=now - timedelta(days=4 - index))
        for index in range(1, 5)
    ]
    profile = _make_podcast_profile(db_session, collection, local_media_profile, count=2, delete_older=True)

    completed_file = tmp_path / "old-completed.m4a"
    completed_file.write_bytes(b"data")
    completed = EpisodeMediaDownload(
        type=MediaType.EPISODE.value,
        media_item_id=episodes[0].id,
        local_media_profile_id=local_media_profile.id,
        download_profile_id=profile.id,
        **available_artifact(),
        file_path=str(completed_file),
    )
    absent = EpisodeMediaDownload(
        type=MediaType.EPISODE.value,
        media_item_id=episodes[1].id,
        local_media_profile_id=local_media_profile.id,
        download_profile_id=profile.id,
        artifact_status=MediaDownloadArtifactStatus.ABSENT.value,
        file_path=str(tmp_path / "old-absent.m4a"),
    )
    kept = EpisodeMediaDownload(
        type=MediaType.EPISODE.value,
        media_item_id=episodes[2].id,
        local_media_profile_id=local_media_profile.id,
        download_profile_id=profile.id,
        **available_artifact(),
        file_path=str(tmp_path / "kept.m4a"),
    )
    db_session.add_all([completed, absent, kept])
    db_session.commit()

    cleanup = cleanup_older_episodes(db_session, profile)
    removed = cleanup.removed
    db_session.commit()
    remove_downloaded_files(list(cleanup.files))

    assert removed == 2
    assert not completed_file.exists()
    rows = {
        row.media_item_id: row
        for row in db_session.query(EpisodeMediaDownload).all()
    }
    assert set(rows) == {episodes[2].id}
    assert rows[episodes[2].id].download_profile_id == profile.id


def test_episode_count_cleanup_keeps_available_files_when_delete_older_is_off(db_session, tmp_path):
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.types.download_profile_types import MediaDownloadArtifactStatus
    from backend.types.media_types import MediaType
    from backend.services.collections import remove_downloaded_files
    from task_manager.tasks.workers.download_profile_worker._helpers import cleanup_older_episodes

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    local_media_profile = _make_local_media_profile(db_session)
    now = datetime.now(timezone.utc)
    completed_episode = _make_episode(db_session, collection, season, index=1, published_at=now - timedelta(days=2))
    absent_episode = _make_episode(db_session, collection, season, index=2, published_at=now - timedelta(days=1))
    _make_episode(db_session, collection, season, index=3, published_at=now)
    profile = _make_podcast_profile(db_session, collection, local_media_profile, count=1, delete_older=False)

    completed_file = tmp_path / "retained-old.m4a"
    completed_file.write_bytes(b"data")
    completed = EpisodeMediaDownload(
        type=MediaType.EPISODE.value,
        media_item_id=completed_episode.id,
        local_media_profile_id=local_media_profile.id,
        download_profile_id=profile.id,
        **available_artifact(),
        file_path=str(completed_file),
    )
    absent = EpisodeMediaDownload(
        type=MediaType.EPISODE.value,
        media_item_id=absent_episode.id,
        local_media_profile_id=local_media_profile.id,
        download_profile_id=profile.id,
        artifact_status=MediaDownloadArtifactStatus.ABSENT.value,
        file_path=str(tmp_path / "stale-absent.m4a"),
    )
    db_session.add_all([completed, absent])
    db_session.commit()

    cleanup = cleanup_older_episodes(db_session, profile)
    removed = cleanup.removed
    db_session.commit()
    remove_downloaded_files(list(cleanup.files))

    assert removed == 1
    assert completed_file.exists()
    rows = {
        row.media_item_id: row
        for row in db_session.query(EpisodeMediaDownload).all()
    }
    assert set(rows) == {completed_episode.id}
    assert rows[completed_episode.id].artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value
    assert rows[completed_episode.id].download_profile_id == profile.id


def _manual(session, episode, local_media_profile, path, **fields):
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.types.media_types import MediaType

    path.write_bytes(b"data")
    download = EpisodeMediaDownload(
        type=MediaType.EPISODE.value, media_item_id=episode.id, local_media_profile_id=local_media_profile.id,
        download_profile_id=None, **available_artifact(), file_path=str(path), **fields,
    )
    session.add(download)
    session.flush()
    return download


@pytest.mark.parametrize("include_manual", [False, True])
def test_cleanup_deletes_manual_downloads_only_when_the_profile_includes_them(db_session, tmp_path, include_manual):
    from backend.db.models import LocalMediaProfile
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.services.collections import remove_downloaded_files
    from task_manager.tasks.workers.download_profile_worker._helpers import cleanup_older_episodes

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    local_media_profile = _make_local_media_profile(db_session)
    other_media_profile = LocalMediaProfile(
        slug="other-audio", name="Other audio", output_template="/other/{{ episode }}.ext",
        preferred_format="format_audio_only",
    )
    db_session.add(other_media_profile)
    now = datetime.now(timezone.utc)
    old, older, newest = (
        _make_episode(db_session, collection, season, index=index, published_at=now - timedelta(days=3 - index))
        for index in range(1, 4)
    )
    profile = _make_podcast_profile(db_session, collection, local_media_profile, count=1, delete_older=True)
    profile.retention_includes_manual = include_manual

    out_of_window = _manual(db_session, old, local_media_profile, tmp_path / "old.m4a")
    kept = _manual(db_session, older, local_media_profile, tmp_path / "kept.m4a", kept=True)
    in_window = _manual(db_session, newest, local_media_profile, tmp_path / "newest.m4a")
    other_library = _manual(db_session, old, other_media_profile, tmp_path / "other.m4a")
    db_session.commit()

    cleanup = cleanup_older_episodes(db_session, profile)
    removed = cleanup.removed
    db_session.commit()
    remove_downloaded_files(list(cleanup.files))

    remaining = {row.id for row in db_session.query(EpisodeMediaDownload).all()}
    if include_manual:
        assert removed == 1
        assert remaining == {kept.id, in_window.id, other_library.id}
        assert not (tmp_path / "old.m4a").exists()
    else:
        assert removed == 0
        assert out_of_window.id in remaining
        assert (tmp_path / "old.m4a").exists()
    assert (tmp_path / "kept.m4a").exists() and (tmp_path / "other.m4a").exists()


def test_cleanup_leaves_a_waiting_manual_download_alone(db_session, tmp_path):
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.types.download_profile_types import MediaDownloadArtifactStatus
    from backend.types.media_types import MediaType
    from task_manager.tasks.workers.download_profile_worker._helpers import cleanup_older_episodes

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    local_media_profile = _make_local_media_profile(db_session)
    now = datetime.now(timezone.utc)
    old = _make_episode(db_session, collection, season, index=1, published_at=now - timedelta(days=1))
    _make_episode(db_session, collection, season, index=2, published_at=now)
    profile = _make_podcast_profile(db_session, collection, local_media_profile, count=1, delete_older=True)
    profile.retention_includes_manual = True
    waiting = EpisodeMediaDownload(
        type=MediaType.EPISODE.value, media_item_id=old.id, local_media_profile_id=local_media_profile.id,
        download_profile_id=None, artifact_status=MediaDownloadArtifactStatus.ABSENT.value,
        file_path=str(tmp_path / "waiting.m4a"),
    )
    db_session.add(waiting)
    db_session.commit()

    assert cleanup_older_episodes(db_session, profile).removed == 0
    assert db_session.get(EpisodeMediaDownload, waiting.id) is not None
