from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

TEMPLATE = "/downloads/shows/{{ collection }}/{{ episode_title }}.ext"


def _new_session() -> tuple[Session, object]:
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine), engine


def _create(**values):
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    return CollectionLocalMediaProfileAPICreate(
        name="Collection audio", output_template=TEMPLATE, preferred_format="format_audio_only", **values,
    )


def test_a_new_profile_is_offered_for_every_source() -> None:
    assert _create().source_keys is None


def test_choosing_some_sources_keeps_them_in_registration_order() -> None:
    assert _create(source_keys=["ytdlp", "dailywire"]).source_keys == ["dailywire", "ytdlp"]


def test_choosing_every_source_also_offers_sources_added_later() -> None:
    assert _create(source_keys=["npo", "ytdlp", "dailywire"]).source_keys is None


def test_a_profile_needs_at_least_one_source() -> None:
    with pytest.raises(ValidationError, match="at least one Source"):
        _create(source_keys=[])


def test_a_source_must_be_able_to_use_the_profile_type() -> None:
    from backend.api.models.movie_local_media_profile import MovieLocalMediaProfileAPICreate

    with pytest.raises(ValidationError, match="ytdlp"):
        MovieLocalMediaProfileAPICreate(
            name="Movies", output_template="/downloads/movies/{{ title }}.ext",
            preferred_format="format_1080p", source_keys=["ytdlp"],
        )


def test_the_profile_stores_its_sources_and_an_update_without_them_keeps_them() -> None:
    from backend.api.endpoints.collection_local_media_profiles.service import (
        create_collection_local_media_profile, update_collection_local_media_profile,
    )
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPIUpdate

    session, engine = _new_session()
    created = create_collection_local_media_profile(session, _create(source_keys=["ytdlp"]))
    assert created.source_keys == ["ytdlp"]

    updated = update_collection_local_media_profile(
        session, created.slug,
        CollectionLocalMediaProfileAPIUpdate(name="Collection audio", output_template=TEMPLATE, preferred_format="format_audio_only"),
    )
    assert updated.source_keys == ["ytdlp"]

    session.close()
    engine.dispose()


def test_a_profile_for_other_sources_cannot_be_chosen() -> None:
    from backend.api.endpoints.collection_local_media_profiles.service import create_collection_local_media_profile
    from backend.types.local_media_profile_types import LocalMediaProfileType
    from backend.utils.local_media_profiles import require_local_media_profile_type

    session, engine = _new_session()
    profile = create_collection_local_media_profile(session, _create(source_keys=["ytdlp"]))

    assert require_local_media_profile_type(session, profile.id, LocalMediaProfileType.COLLECTION, "ytdlp").id == profile.id
    with pytest.raises(HTTPException, match="not available for this Source"):
        require_local_media_profile_type(session, profile.id, LocalMediaProfileType.COLLECTION, "dailywire")

    session.close()
    engine.dispose()
