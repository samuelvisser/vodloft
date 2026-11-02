from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def db_session():
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    session = Session(engine)
    Base.metadata.create_all(engine)
    yield session
    session.close()
    engine.dispose()


def _make_collection(session: Session, slug: str = "collection"):
    from backend.db.models import Collection
    from backend.types.collection_types import EpisodeIdentifier, CollectionType

    collection = Collection(
        source_key="dailywire",
        uuid=f"{slug}-uuid",
        slug=slug,
        title="Collection",
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


def _make_local_media_profile(session: Session, slug: str):
    from backend.db.models import LocalMediaProfile

    profile = LocalMediaProfile(
        slug=slug,
        name=slug,
        output_template=f"/downloads/{slug}/{{{{ collection }}}}/{{{{ episode }}}}.ext",
        preferred_format="format_1080p",
    )
    session.add(profile)
    session.flush()
    return profile


def _make_download_profile(session: Session, collection, local_media_profile, episode_types: list[str]):
    from backend.db.models.download_profile import DownloadProfile

    profile = DownloadProfile(
        collection=collection,
        local_media_profile=local_media_profile,
        enable_profile=True,
        ep_id_type_list=episode_types,
        download_with_countdown=False,
        redownload_final=False,
        download_days_in_past=0,
        download_episode_count=0,
        delete_older_episodes=False,
    )
    session.add(profile)
    session.flush()
    return profile


def _make_episode(session: Session, collection):
    from backend.db.models import Episode, Season

    season = Season(collection=collection, index=1, slug="season-1", name="Season 1")
    episode = Episode(
        source_key="dailywire",
        uuid="episode-uuid",
        type="episode",
        collection=collection,
        season=season,
        index=1,
        episode_identifier="ep.1",
        slug="episode-1",
        title="Episode 1",
        duration=100,
        publish_status="published_final",
        sharing_url="https://example.test/episode-1",
    )
    session.add_all([season, episode])
    session.flush()
    return episode


def test_same_collection_and_media_profile_allows_non_overlapping_episode_types(db_session: Session):
    collection = _make_collection(db_session)
    local_media_profile = _make_local_media_profile(db_session, "video")

    episode_profile = _make_download_profile(db_session, collection, local_media_profile, ["ep"])
    auxiliary_profile = _make_download_profile(db_session, collection, local_media_profile, ["aux"])

    assert episode_profile.id != auxiliary_profile.id


def test_overlapping_episode_type_is_rejected_for_same_collection_and_media_profile(db_session: Session):
    from backend.api.endpoints.download_profiles.service import require_unique_download_profile_episode_types

    collection = _make_collection(db_session)
    local_media_profile = _make_local_media_profile(db_session, "video")
    _make_download_profile(db_session, collection, local_media_profile, ["ep"])

    with pytest.raises(HTTPException) as exc_info:
        require_unique_download_profile_episode_types(
            db_session,
            collection_id=collection.id,
            local_media_profile_id=local_media_profile.id,
            episode_types=["ep", "aux"],
        )

    assert exc_info.value.status_code == 409
    assert "ep" in str(exc_info.value.detail)


def test_episode_type_can_be_reused_with_different_media_profile(db_session: Session):
    from backend.api.endpoints.download_profiles.service import require_unique_download_profile_episode_types

    collection = _make_collection(db_session)
    first_media_profile = _make_local_media_profile(db_session, "video-1080")
    second_media_profile = _make_local_media_profile(db_session, "video-720")
    _make_download_profile(db_session, collection, first_media_profile, ["ep"])

    require_unique_download_profile_episode_types(
        db_session,
        collection_id=collection.id,
        local_media_profile_id=second_media_profile.id,
        episode_types=["ep"],
    )


def test_profile_update_does_not_conflict_with_its_own_episode_types(db_session: Session):
    from backend.api.endpoints.download_profiles.service import require_unique_download_profile_episode_types

    collection = _make_collection(db_session)
    local_media_profile = _make_local_media_profile(db_session, "video")
    profile = _make_download_profile(db_session, collection, local_media_profile, ["ep", "aux"])

    require_unique_download_profile_episode_types(
        db_session,
        collection_id=collection.id,
        local_media_profile_id=local_media_profile.id,
        episode_types=["ep", "aux"],
        exclude_profile_id=profile.id,
    )


def test_existing_download_moves_to_profile_that_now_owns_episode_type(db_session: Session):
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.types.download_profile_types import MediaDownloadArtifactStatus
    from task_manager.tasks.workers.download_profile_worker._helpers import ensure_episode_download

    collection = _make_collection(db_session)
    local_media_profile = _make_local_media_profile(db_session, "video")
    previous_profile = _make_download_profile(db_session, collection, local_media_profile, ["aux"])
    current_profile = _make_download_profile(db_session, collection, local_media_profile, ["ep"])
    episode = _make_episode(db_session, collection)

    download = EpisodeMediaDownload(
        type="episode",
        media_item_id=episode.id,
        local_media_profile_id=local_media_profile.id,
        download_profile_id=previous_profile.id,
        artifact_status=MediaDownloadArtifactStatus.ABSENT.value,
        file_path="/downloads/episode.mp4",
        # Suppressed, so the check stays about ownership and queues nothing.
        automatic_retry_suppressed=True,
        downloaded_publish_status="published_final",
    )
    db_session.add(download)
    db_session.flush()

    action = ensure_episode_download(db_session, current_profile, episode)

    assert action.needs_operation is False
    assert download.download_profile_id == current_profile.id
