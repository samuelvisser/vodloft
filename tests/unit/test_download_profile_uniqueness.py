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


def _make_download_profile(session: Session, collection, local_media_profile):
    from backend.db.models.download_profile import DownloadProfile

    profile = DownloadProfile(
        collection=collection,
        local_media_profile=local_media_profile,
        enable_profile=True,
        download_with_countdown=False,
        redownload_final=False,
        delete_older_episodes=False,
    )
    session.add(profile)
    session.flush()
    return profile


def test_a_second_profile_for_the_same_collection_and_media_profile_is_refused(db_session: Session):
    from sqlalchemy.exc import IntegrityError

    from backend.api.endpoints.download_profiles.service import require_one_profile_per_local_media_profile

    collection = _make_collection(db_session)
    local_media_profile = _make_local_media_profile(db_session, "video")
    _make_download_profile(db_session, collection, local_media_profile)

    with pytest.raises(HTTPException) as exc_info:
        require_one_profile_per_local_media_profile(
            db_session, collection_id=collection.id, local_media_profile_id=local_media_profile.id,
        )
    assert exc_info.value.status_code == 409
    # The database refuses it too.
    with pytest.raises(IntegrityError):
        _make_download_profile(db_session, collection, local_media_profile)


def test_another_media_profile_gets_its_own_download_profile(db_session: Session):
    from backend.api.endpoints.download_profiles.service import require_one_profile_per_local_media_profile

    collection = _make_collection(db_session)
    first_media_profile = _make_local_media_profile(db_session, "video-1080")
    second_media_profile = _make_local_media_profile(db_session, "video-720")
    _make_download_profile(db_session, collection, first_media_profile)

    require_one_profile_per_local_media_profile(
        db_session, collection_id=collection.id, local_media_profile_id=second_media_profile.id,
    )
    assert _make_download_profile(db_session, collection, second_media_profile).id


def test_a_profile_update_does_not_conflict_with_itself(db_session: Session):
    from backend.api.endpoints.download_profiles.service import require_one_profile_per_local_media_profile

    collection = _make_collection(db_session)
    local_media_profile = _make_local_media_profile(db_session, "video")
    profile = _make_download_profile(db_session, collection, local_media_profile)

    require_one_profile_per_local_media_profile(
        db_session, collection_id=collection.id, local_media_profile_id=local_media_profile.id,
        exclude_profile_id=profile.id,
    )
