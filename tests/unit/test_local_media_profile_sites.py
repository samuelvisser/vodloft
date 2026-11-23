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

    from backend.services.sites import add_suggested_sites

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    # The Sites a user picked in onboarding.
    add_suggested_sites(session, ("youtube", "twitch", "tiktok", "soundcloud", "dailywire"))
    return session, engine


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
    from backend.api.endpoints.video_local_media_profiles.service import create_video_local_media_profile
    from backend.api.models.video_local_media_profile import VideoLocalMediaProfileAPICreate

    session, engine = _new_session()
    _see_site(session, "vimeo", "Vimeo")
    created = create_collection_local_media_profile(session, _create())
    assert created.site_keys == ["dailywire", "soundcloud", "tiktok", "twitch", "vimeo", "youtube"]
    assert created.include_upcoming_sites is True

    # A Video profile keeps single videos and movies, so it starts with every Site too.
    videos = create_video_local_media_profile(session, VideoLocalMediaProfileAPICreate(
        name="Videos", output_template="/downloads/videos/{{ title }}.ext", preferred_format="format_1080p",
    ))
    assert videos.site_keys == ["dailywire", "soundcloud", "tiktok", "twitch", "vimeo", "youtube"]
    assert videos.include_upcoming_sites is True

    session.close()
    engine.dispose()


def test_chosen_sites_are_kept_once_each() -> None:
    assert _create(site_keys=["youtube", "dailywire", "youtube"]).site_keys == ["youtube", "dailywire"]


def test_a_profile_needs_a_site_or_upcoming_sites() -> None:
    assert _create(site_keys=[], include_upcoming_sites=True).site_keys == []
    with pytest.raises(ValidationError, match="at least one Site"):
        _create(site_keys=[], include_upcoming_sites=False)


def test_only_the_daily_wire_has_movies() -> None:
    from backend.services.local_media_profile_sites import movie_site_keys

    session, engine = _new_session()
    _see_site(session, "vimeo", "Vimeo")
    assert movie_site_keys(session) == ["dailywire"]

    session.close()
    engine.dispose()


def test_a_site_has_movies_by_its_contract(monkeypatch) -> None:
    from dataclasses import replace

    from backend.services import local_media_profile_sites
    from sources import site_of

    youtube = site_of("youtube")
    monkeypatch.setattr(local_media_profile_sites, "site_of", lambda key: replace(youtube, movies=True) if key == "youtube" else site_of(key))
    # A Source that fetches the Site still needs movies of its own: yt-dlp has none.
    assert not local_media_profile_sites.site_has_movies("youtube")
    assert local_media_profile_sites.site_has_movies("dailywire")
    assert not site_of("youtube").movies


def test_a_profile_only_for_movies_shows_once_a_site_has_movies() -> None:
    from backend.api.endpoints.local_media_profiles.service import get_local_media_profile_views_page
    from backend.api.endpoints.video_local_media_profiles.service import create_video_local_media_profile
    from backend.api.models.profile_list import LocalMediaProfileListQuery
    from backend.api.models.video_local_media_profile import VideoLocalMediaProfileAPICreate
    from backend.services.sites import remove_site

    session, engine = _new_session()
    for scope in ("movies", "videos"):
        create_video_local_media_profile(session, VideoLocalMediaProfileAPICreate(
            name=scope.title(), output_template=f"/downloads/{scope}/{{{{ title }}}}.ext", preferred_format="format_1080p",
            video_scope=scope,
        ))
    names = lambda: [view.profile.name for view in get_local_media_profile_views_page(session, LocalMediaProfileListQuery()).items]
    assert names() == ["Movies", "Videos"]

    remove_site(session, "dailywire")
    assert names() == ["Videos"]

    session.close()
    engine.dispose()


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
    assert by_key["dailywire"]["profileTypes"] == ["collection", "video"]
    assert by_key["youtube"]["profileTypes"] == ["collection", "video"]
    assert by_key["youtube"]["downloadOptions"]["hlsBundle"] is True
    assert by_key["dailywire"]["movies"] is True
    assert by_key["youtube"]["movies"] is False
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


def test_a_profile_only_for_movies_only_takes_new_sites_with_movies() -> None:
    from backend.db.initial_seed import _seed_local_media_profiles
    from backend.db.models import LocalMediaProfileBase
    from backend.services.sites import add_suggested_sites

    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    # A new VODLoft has no Sites yet when its profiles are made.
    _seed_local_media_profiles(session)
    session.flush()

    add_suggested_sites(session, ("youtube", "dailywire"))
    _see_site(session, "rumble", "Rumble")
    session.flush()

    profiles = {profile.slug: profile.site_keys for profile in session.query(LocalMediaProfileBase)}
    assert profiles["vodloft-movies"] == ["dailywire"]
    assert profiles["vodloft-videos"] == ["youtube", "dailywire", "rumble"]

    session.close()
    engine.dispose()
