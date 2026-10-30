from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .core import get_session, load_database_models


# Data every brand-new VODLoft installation should start with belongs here.
#
# This module runs only after Alembic has brought a fresh database to the
# current schema. Keep schema/data transformations for existing installations
# in migrations; keep development/demo fixtures in backend.db.fake_data.
_SHOW_VIDEO_TEMPLATE = (
    "/downloads/shows/{{ show_title }}/{{ season_name }}/{{ episode_title }}.ext"
)
_SHOW_AUDIO_TEMPLATE = (
    "/downloads/podcasts/{{ show_title }}/"
    "{{ episode_published_date }} - {{ episode_title }}.ext"
)
_MOVIE_TEMPLATE = (
    "{% set output_year = ' (' ~ movie_year ~ ')' if movie_year %}"
    "/downloads/movies/{{ movie_title }}{{ output_year }}/"
    "{{ movie_title }}{{ output_year }}"
    "{% if media_type != 'movie' %}-{{ media_type }} [{{ title }}]{% endif %}"
    "{% if media_type != 'movie' %}-{{ media_type }}{% endif %}.ext"
)

_VIDEO_TEMPLATE = (
    "{% set output_date = date ~ ' - ' if date %}"
    "/downloads/videos/{{ author or source }}/"
    "{{ output_date }}{{ title }} [{{ slug }}].ext"
)


def _seed_local_media_profiles(session: Session) -> None:
    from backend.db.models import (
        LocalMediaProfileBase,
        MovieLocalMediaProfile,
        ShowLocalMediaProfile,
        VideoLocalMediaProfile,
    )

    profiles = (
        ShowLocalMediaProfile(
            slug="vodloft-shows-video",
            name="VODLoft Shows (Video)",
            subtitle_mode="sidecar",
            output_template=_SHOW_VIDEO_TEMPLATE,
            preferred_format="format_1080p",
        ),
        ShowLocalMediaProfile(
            slug="vodloft-shows-audio",
            name="VODLoft Shows (Audio)",
            subtitle_mode="sidecar",
            output_template=_SHOW_AUDIO_TEMPLATE,
            preferred_format="format_audio_only",
        ),
        MovieLocalMediaProfile(
            slug="vodloft-movies",
            name="VODLoft Movies",
            subtitle_mode="sidecar",
            output_template=_MOVIE_TEMPLATE,
            preferred_format="format_1080p",
        ),
        VideoLocalMediaProfile(
            slug="vodloft-videos",
            name="VODLoft Videos",
            output_template=_VIDEO_TEMPLATE,
            preferred_format="format_1080p",
        ),
    )
    slugs = tuple(profile.slug for profile in profiles)
    existing_slugs = set(session.scalars(
        select(LocalMediaProfileBase.slug).where(
            LocalMediaProfileBase.slug.in_(slugs)
        )
    ))
    session.add_all(
        profile
        for profile in profiles
        if profile.slug not in existing_slugs
    )


_INITIAL_SEED_STEPS: tuple[Callable[[Session], None], ...] = (
    _seed_local_media_profiles,
)


def seed_initial_database() -> None:
    """Populate the application data for a brand-new VODLoft database."""
    load_database_models()

    session = get_session()
    try:
        for seed_step in _INITIAL_SEED_STEPS:
            seed_step(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
