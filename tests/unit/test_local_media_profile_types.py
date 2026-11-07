from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.services.errors import ServiceError

from config.settings.site_settings import DEFAULT_SPONSORBLOCK_SEGMENTS

# What every Download Profile request names; the UI starts them from the Site's settings.
PROFILE_CHOICES = dict(
    auto_subtitles="fallback", sponsorblock_enabled=False, sponsorblock_segments=dict(DEFAULT_SPONSORBLOCK_SEGMENTS),
    upgrade_check=False, upgrade_after_days=7, upgrade_repeat="once", upgrade_improvements=[], upgrade_length_minutes=5,
)



def _new_session() -> tuple[Session, object]:
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine), engine


def test_local_media_profile_models_are_polymorphic_and_unique_by_type() -> None:
    from backend.db.models import (
        LocalMediaProfileBase,
        MovieLocalMediaProfile,
        CollectionLocalMediaProfile,
    )

    session, engine = _new_session()
    shared_settings = {
        "output_template": "/downloads/library/{{ title }}.ext",
        "preferred_format": "format_1080p",
    }
    collection_profile = CollectionLocalMediaProfile(
        slug="collection-video", name="Collection video", **shared_settings,
    )
    movie_profile = MovieLocalMediaProfile(
        slug="movie-video", name="Movie video", **shared_settings,
    )
    session.add_all([collection_profile, movie_profile])
    session.commit()

    profiles = session.query(LocalMediaProfileBase).order_by(LocalMediaProfileBase.id).all()
    assert isinstance(profiles[0], CollectionLocalMediaProfile)
    assert isinstance(profiles[1], MovieLocalMediaProfile)
    assert [profile.type for profile in profiles] == ["collection", "movie"]

    # Download behavior is not part of the profile identity. The same type,
    # output template and preferred format must remain unique even when the
    # storage-mode override differs.
    session.add(CollectionLocalMediaProfile(
        slug="duplicate-collection-video",
        name="Duplicate collection video",
        download_mode="temporary",
        **shared_settings,
    ))
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()
    session.close()
    engine.dispose()


def test_local_media_profile_api_enforces_type_specific_formats_and_placeholders() -> None:
    from backend.api.models.movie_local_media_profile import MovieLocalMediaProfileAPICreate
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    movie = MovieLocalMediaProfileAPICreate(
        type="movie",
        name="Movie 1080p",
        output_template="/downloads/movies/{{ movie_extended_title }}/{{ title }}.ext",
        preferred_format="format_1080p",
    )
    assert movie.type == "movie"
    assert movie.output_template == "/downloads/movies/{{ movie_extended_title }}/{{ title }}.ext"

    with pytest.raises(ValidationError, match="require a normal video format"):
        MovieLocalMediaProfileAPICreate(
            name="Movie audio",
            output_template="/downloads/movies/{{ movie_slug }}.ext",
            preferred_format="format_audio_only",
        )

    hls_collection = CollectionLocalMediaProfileAPICreate(
        name="Podcast HLS",
        output_template="/downloads/podcasts/{{ collection }}/{{ episode }}.ext",
        preferred_format="format_hls",
    )
    assert hls_collection.preferred_format == "format_hls"

    with pytest.raises(ValidationError, match="normal video format"):
        MovieLocalMediaProfileAPICreate(
            name="Movie HLS",
            output_template="/downloads/movies/{{ movie_slug }}/{{ title }}.ext",
            preferred_format="format_hls",
        )

    with pytest.raises(ValidationError, match="episode"):
        MovieLocalMediaProfileAPICreate(
            name="Wrong movie template",
            output_template="/downloads/movies/{{ episode }}.ext",
            preferred_format="format_720p",
        )

    with pytest.raises(ValidationError, match="dw_id"):
        MovieLocalMediaProfileAPICreate(
            name="Rotating ID template",
            output_template="/downloads/movies/{{ movie_title }}/{{ dw_id }}.ext",
            preferred_format="format_1080p",
        )

    with pytest.raises(ValidationError, match="movie_dw_id"):
        MovieLocalMediaProfileAPICreate(
            name="Rotating parent ID template",
            output_template="/downloads/movies/{{ movie_dw_id }}/{{ title }}.ext",
            preferred_format="format_1080p",
        )

    with pytest.raises(ValidationError, match="movie"):
        CollectionLocalMediaProfileAPICreate(
            name="Wrong collection template",
            output_template="/downloads/shows/{{ movie_slug }}.ext",
            preferred_format="format_audio_only",
        )


def test_local_media_profile_service_rejects_duplicate_and_colliding_outputs() -> None:
    from backend.api.endpoints.movie_local_media_profiles.service import (
        create_movie_local_media_profile,
    )
    from backend.api.endpoints.collection_local_media_profiles.service import (
        create_collection_local_media_profile,
        update_collection_local_media_profile,
    )
    from backend.api.models.movie_local_media_profile import (
        MovieLocalMediaProfileAPICreate,
    )
    from backend.api.models.collection_local_media_profile import (
        CollectionLocalMediaProfileAPICreate,
        CollectionLocalMediaProfileAPIUpdate,
    )

    session, engine = _new_session()
    common = {
        "output_template": "/downloads/library/{{ title }}.ext",
        "preferred_format": "format_1080p",
    }
    collection = create_collection_local_media_profile(
        session,
        CollectionLocalMediaProfileAPICreate(name="Collection", **common),
    )
    movie = create_movie_local_media_profile(
        session,
        MovieLocalMediaProfileAPICreate(name="Movie", **common),
    )
    assert collection.type == "collection"
    assert movie.type == "movie"

    # Exact uniqueness remains type + output template + preferred format. A
    # different Local Media Profile storage override does not make it unique.
    with pytest.raises(ServiceError) as exact_error:
        create_collection_local_media_profile(
            session,
            CollectionLocalMediaProfileAPICreate(
                type="collection",
                name="Duplicate",
                download_mode="temporary",
                **common,
            ),
        )
    assert exact_error.value.status_code == 409
    assert "output path template and preferred format" in str(exact_error.value)

    # A different Jinja string that renders to the same path is also a conflict.
    equivalent_template = (
        "{% set media_title = title %}"
        "/downloads/library/{{ media_title }}.ext"
    )
    with pytest.raises(ServiceError) as semantic_error:
        create_collection_local_media_profile(
            session,
            CollectionLocalMediaProfileAPICreate(
                type="collection",
                name="Equivalent",
                output_template=equivalent_template,
                preferred_format="format_1080p",
            ),
        )
    assert semantic_error.value.status_code == 409
    assert semantic_error.value.kind == "output_path_collision"
    assert "same file as Local Media Profile 'Collection'" in str(semantic_error.value)

    # Video qualities still resolve to the same concrete .mp4 path, so they may
    # not share an effective output even though preferred_format differs.
    with pytest.raises(ServiceError) as video_quality_error:
        create_collection_local_media_profile(
            session,
            CollectionLocalMediaProfileAPICreate(
                type="collection",
                name="Collection 720p",
                output_template=common["output_template"],
                preferred_format="format_720p",
            ),
        )
    assert video_quality_error.value.status_code == 409
    assert video_quality_error.value.kind == "output_path_collision"

    # Audio and video may safely use the same template because their concrete
    # output extensions differ.
    audio = create_collection_local_media_profile(
        session,
        CollectionLocalMediaProfileAPICreate(
            name="Collection audio",
            output_template=common["output_template"],
            preferred_format="format_audio_only",
        ),
    )
    assert audio.preferred_format == "format_audio_only"

    hls = create_collection_local_media_profile(
        session,
        CollectionLocalMediaProfileAPICreate(
            name="Collection adaptive HLS",
            output_template=common["output_template"],
            preferred_format="format_hls",
        ),
    )
    assert hls.preferred_format == "format_hls"

    distinct = create_collection_local_media_profile(
        session,
        CollectionLocalMediaProfileAPICreate(
            name="Distinct",
            output_template="/downloads/distinct/{{ title }}.ext",
            preferred_format="format_1080p",
        ),
    )
    with pytest.raises(ServiceError) as update_error:
        update_collection_local_media_profile(
            session,
            distinct.slug,
            CollectionLocalMediaProfileAPIUpdate(
                type="collection",
                name="Distinct",
                output_template=equivalent_template,
                preferred_format="format_1080p",
            ),
        )
    assert update_error.value.status_code == 409
    assert update_error.value.kind == "output_path_collision"

    session.close()
    engine.dispose()


def test_movie_output_template_uses_movie_metadata(tmp_path: Path, monkeypatch) -> None:
    from backend.db.models import Movie
    from backend.types.media_types import MediaType
    from backend.utils.output_template import resolve_movie_output_path
    from config import get_settings

    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    movie = Movie(
        source_key="dailywire",
        uuid="movie-uuid",
        type=MediaType.MOVIE.value,
        slug="a-movie",
        title="A Movie",
        extended_title="A Movie | A Daily Wire Original",
        author_name="A Director",
        mature_rating="PG-13",
        description=None,
        duration=5400,
    )

    result = resolve_movie_output_path(
        "/downloads/{{ movie_author }}/{{ movie_extended_title }} [{{ rating }}]/{{ movie_slug }}.ext",
        movie=movie,
        extension="mp4",
    )

    assert result == (
        tmp_path
        / "A Director"
        / "A Movie ｜ A Daily Wire Original [PG-13]"
        / "a-movie.mp4"
    ).resolve()


def test_manual_downloads_reject_the_wrong_local_media_profile_type() -> None:
    from backend.api.endpoints.download_profiles.service import create_download_profile
    from backend.api.endpoints.media_downloads.service import (
        create_episode_download,
        create_movie_download,
    )
    from backend.api.models.media_download import EpisodeDownloadAPICreate, MediaDownloadAPICreate
    from backend.api.models.download_profile import DownloadProfileAPICreate
    from backend.db.models import (
        Episode,
        MovieLocalMediaProfile,
        Season,
        Collection,
        CollectionLocalMediaProfile,
    )
    from backend.types.collection_types import EpisodeIdentifier, CollectionType
    from backend.utils.helpers import generate_uuid
    from backend.db.models import Movie

    session, engine = _new_session()
    collection_profile = CollectionLocalMediaProfile(
        slug="collections",
        name="Collections",
        output_template="/downloads/shows/{{ collection }}/{{ episode }}.ext",
        preferred_format="format_1080p",
    )
    movie_profile = MovieLocalMediaProfile(
        slug="movies",
        name="Movies",
        output_template="/downloads/movies/{{ movie_slug }}.ext",
        preferred_format="format_1080p",
    )
    collection = Collection(
        source_key="dailywire",
        uuid="collection-uuid",
        slug="collection",
        title="Collection",
        description=None,
        sharing_url="https://example.test/collection",
        membership_level="FREE",
        type=CollectionType.PODCAST.value,
        episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Host",
        author_slug="host",
    )
    season = Season(collection=collection, index=1, slug="season-1", name="One")
    episode = Episode(
        source_key="dailywire",
        uuid=generate_uuid(),
        type="episode",
        collection=collection,
        season=season,
        index=1,
        episode_identifier="ep.1",
        slug="ep-1",
        title="Episode 1",
        duration=100.0,
        publish_status="published_final",
        sharing_url="https://example.test/ep-1",
    )
    session.add_all([collection_profile, movie_profile, collection, season, episode])
    session.commit()

    with pytest.raises(HTTPException, match="Collection Local Media Profile") as episode_error:
        create_episode_download(
            session,
            episode.slug,
            EpisodeDownloadAPICreate(local_media_profile_id=movie_profile.id),
        )
    assert episode_error.value.status_code == 422

    movie = Movie(source_key="dailywire", uuid=generate_uuid(), slug="a-movie", title="A Movie", sharing_url="https://example.test/a-movie")
    session.add(movie)
    session.flush()
    with pytest.raises(HTTPException, match="Movie Local Media Profile") as movie_error:
        create_movie_download(
            session,
            movie,
            MediaDownloadAPICreate(local_media_profile_id=collection_profile.id),
        )
    assert movie_error.value.status_code == 422

    with pytest.raises(HTTPException, match="Collection Local Media Profile") as profile_error:
        create_download_profile(
            session,
            DownloadProfileAPICreate(
                collection_id=collection.id,
                local_media_profile_id=movie_profile.id,
                enable_profile=True,
                download_with_countdown=False,
                redownload_final=False,
                delete_older_episodes=False,
                **PROFILE_CHOICES,
            ),
        )
    assert profile_error.value.status_code == 422

    session.close()
    engine.dispose()
