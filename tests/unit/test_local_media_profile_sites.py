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

    return CollectionLocalMediaProfileAPICreate(**{
        "name": "Collection audio", "output_template": TEMPLATE, "preferred_format": "format_audio_only", **values,
    })


def _see_site(session: Session, key: str, name: str) -> None:
    from backend.services.sites import site_record
    from sources import Site

    site_record(session, Site(key, name))


def test_a_new_profile_starts_with_every_known_site_and_upcoming_sites() -> None:
    from backend.api.endpoints.collection_local_media_profiles.service import create_collection_local_media_profile
    from backend.api.endpoints.movie_local_media_profiles.service import create_movie_local_media_profile
    from backend.api.models.movie_local_media_profile import MovieLocalMediaProfileAPICreate

    session, engine = _new_session()
    _see_site(session, "vimeo", "Vimeo")
    created = create_collection_local_media_profile(session, _create())
    assert created.site_keys == ["dailywire", "npo", "vimeo", "youtube"]
    assert created.include_upcoming_sites is True

    # Only The Daily Wire has movies.
    movies = create_movie_local_media_profile(session, MovieLocalMediaProfileAPICreate(
        name="Movies", output_template="/downloads/movies/{{ title }}.ext", preferred_format="format_1080p",
    ))
    assert movies.site_keys == ["dailywire"]

    session.close()
    engine.dispose()


def test_chosen_sites_are_kept_once_each() -> None:
    assert _create(site_keys=["youtube", "dailywire", "youtube"]).site_keys == ["youtube", "dailywire"]


def test_a_profile_needs_a_site_or_upcoming_sites() -> None:
    assert _create(site_keys=[], include_upcoming_sites=True).site_keys == []
    with pytest.raises(ValidationError, match="at least one Site"):
        _create(site_keys=[], include_upcoming_sites=False)


def test_a_site_must_be_able_to_use_the_profile_type() -> None:
    from backend.api.models.movie_local_media_profile import MovieLocalMediaProfileAPICreate

    with pytest.raises(ValidationError, match="youtube"):
        MovieLocalMediaProfileAPICreate(
            name="Movies", output_template="/downloads/movies/{{ title }}.ext",
            preferred_format="format_1080p", site_keys=["youtube"],
        )


def test_an_update_without_sites_keeps_them() -> None:
    from backend.api.endpoints.collection_local_media_profiles.service import (
        create_collection_local_media_profile, update_collection_local_media_profile,
    )
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPIUpdate

    session, engine = _new_session()
    created = create_collection_local_media_profile(session, _create(site_keys=["youtube"], include_upcoming_sites=False))
    updated = update_collection_local_media_profile(
        session, created.slug,
        CollectionLocalMediaProfileAPIUpdate(name="Collection audio", output_template=TEMPLATE, preferred_format="format_audio_only"),
    )
    assert updated.site_keys == ["youtube"]
    assert updated.include_upcoming_sites is False

    session.close()
    engine.dispose()


def test_a_new_site_joins_the_profiles_that_include_upcoming_sites() -> None:
    from backend.api.endpoints.collection_local_media_profiles.service import create_collection_local_media_profile
    from backend.db.models import LocalMediaProfileBase

    session, engine = _new_session()
    upcoming = create_collection_local_media_profile(session, _create(site_keys=["youtube"]))
    fixed = create_collection_local_media_profile(session, _create(
        name="Fixed", output_template="/downloads/fixed/{{ episode_title }}.ext", site_keys=["youtube"],
        include_upcoming_sites=False,
    ))

    _see_site(session, "rumble", "Rumble")
    # The Daily Wire was known before, so the profile that left it out still leaves it out.
    _see_site(session, "dailywire", "The Daily Wire")
    session.flush()

    assert session.get(LocalMediaProfileBase, upcoming.id).site_keys == ["youtube", "rumble"]
    assert session.get(LocalMediaProfileBase, fixed.id).site_keys == ["youtube"]

    session.close()
    engine.dispose()


def test_a_profile_for_other_sites_cannot_be_chosen() -> None:
    from backend.api.endpoints.collection_local_media_profiles.service import create_collection_local_media_profile
    from backend.types.local_media_profile_types import LocalMediaProfileType
    from backend.utils.local_media_profiles import require_local_media_profile_type

    session, engine = _new_session()
    profile = create_collection_local_media_profile(session, _create(site_keys=["youtube"]))

    assert require_local_media_profile_type(session, profile.id, LocalMediaProfileType.COLLECTION, "youtube").id == profile.id
    # A Site VODLoft has not seen yet is one of the upcoming Sites.
    assert require_local_media_profile_type(session, profile.id, LocalMediaProfileType.COLLECTION, "vimeo").id == profile.id
    with pytest.raises(HTTPException, match="not available for this Site"):
        require_local_media_profile_type(session, profile.id, LocalMediaProfileType.COLLECTION, "dailywire")

    session.close()
    engine.dispose()


def test_the_sites_listing_says_which_profile_types_each_site_takes() -> None:
    from backend.api.models.local_media_profile import LocalMediaProfileSitesAPIRead
    from backend.services.local_media_profile_sites import profile_sites

    session, engine = _new_session()
    read = LocalMediaProfileSitesAPIRead.model_validate(profile_sites(session)).model_dump(by_alias=True)
    by_key = {site["key"]: site for site in read["sites"]}
    assert by_key["dailywire"]["profileTypes"] == ["collection", "movie", "video"]
    assert by_key["youtube"]["profileTypes"] == ["collection", "video"]
    assert by_key["youtube"]["downloadOptions"]["hlsBundle"] is True
    assert read["upcomingProfileTypes"] == ["collection", "video"]

    session.close()
    engine.dispose()


def test_keeping_every_sponsorblock_type_saves_sponsorblock_off():
    from backend.services.local_media_profile_inputs import CollectionLocalMediaProfileInput
    from config.settings.site_settings import DEFAULT_SPONSORBLOCK_SEGMENTS

    body = {
        "name": "P", "preferred_format": "format_1080p", "output_template": "/downloads/{{ collection }}/{{ episode }}.ext",
        "sponsorblock_enabled": True, "sponsorblock_segments": DEFAULT_SPONSORBLOCK_SEGMENTS,
    }
    kept = {category: "keep" for category in DEFAULT_SPONSORBLOCK_SEGMENTS}
    assert CollectionLocalMediaProfileInput.model_validate({**body, "sponsorblock_segments": kept}).sponsorblock_enabled is False
    assert CollectionLocalMediaProfileInput.model_validate(body).sponsorblock_enabled is True
    with pytest.raises(ValueError):
        CollectionLocalMediaProfileInput.model_validate({**body, "sponsorblock_segments": {**kept, "chapter": "cut"}})
    with pytest.raises(ValueError):
        CollectionLocalMediaProfileInput.model_validate({**body, "sponsorblock_segments": {"sponsor": "cut"}})
    # Left out, an update keeps the profile's own.
    assert {"auto_subtitles", "sponsorblock_enabled", "sponsorblock_segments"} <= (
        CollectionLocalMediaProfileInput.model_validate({**body, "sponsorblock_enabled": None, "sponsorblock_segments": None})
        .fields_kept_on_update()
    )
