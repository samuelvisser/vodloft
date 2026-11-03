from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .core import get_session, load_database_models


# Data every brand-new VODLoft installation should start with belongs here.
#
# This module runs only after Alembic has brought a fresh database to the
# current schema. Keep schema/data transformations for existing installations
# in migrations; keep development/demo fixtures in backend.db.fake_data.
_COLLECTION_VIDEO_TEMPLATE = (
    "/downloads/shows/{{ collection_title }}/{{ season_name }}/{{ episode_title }}.ext"
)
_COLLECTION_AUDIO_TEMPLATE = (
    "/downloads/podcasts/{{ collection_title }}/"
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


def _add_missing_profiles(session: Session, profiles) -> None:
    from backend.db.models import LocalMediaProfileBase

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


def _seed_local_media_profiles(session: Session) -> None:
    from backend.db.models import MovieLocalMediaProfile, VideoLocalMediaProfile

    _add_missing_profiles(session, (
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
    ))


_FRESH_START_PROFILE_SLUGS = ("vodloft-collections-video", "vodloft-collections-audio")


def seed_fresh_start_profiles(session: Session) -> None:
    """The default Collection profiles, for a library that starts fresh instead of importing one.

    Onboarding adds them once a fresh library first needs one, such as for its first collection, or
    when it finishes without an import, so a library imported during onboarding only holds the
    imported profiles (plus Movies and Videos).
    """
    from backend.db.models import CollectionLocalMediaProfile

    _add_missing_profiles(session, (
        CollectionLocalMediaProfile(
            slug=_FRESH_START_PROFILE_SLUGS[0],
            name="VODLoft Collections (Video)",
            subtitle_mode="sidecar",
            output_template=_COLLECTION_VIDEO_TEMPLATE,
            preferred_format="format_1080p",
        ),
        CollectionLocalMediaProfile(
            slug=_FRESH_START_PROFILE_SLUGS[1],
            name="VODLoft Collections (Audio)",
            subtitle_mode="sidecar",
            output_template=_COLLECTION_AUDIO_TEMPLATE,
            preferred_format="format_audio_only",
        ),
    ))


def remove_fresh_start_profiles(session: Session) -> None:
    """Take the default Collection profiles away again, for a person who goes back in onboarding
    to choose between starting fresh and importing."""
    from backend.db.models import CollectionLocalMediaProfile

    for profile in session.scalars(
        select(CollectionLocalMediaProfile).where(CollectionLocalMediaProfile.slug.in_(_FRESH_START_PROFILE_SLUGS))
    ):
        session.delete(profile)


def _seed_notification_rules(session: Session) -> None:
    from backend.services.notifications.rules import restore_default_rules

    restore_default_rules(session)


def _mark_background_migrations_done(session: Session) -> None:
    """A new database has no historical data to repair, so it starts at the latest background migration."""
    from backend.db.background_migrations import get_background_migration_head_revision
    from backend.db.models import Settings

    session.execute(update(Settings).values(background_migration_version=get_background_migration_head_revision()))


_INITIAL_SEED_STEPS: tuple[Callable[[Session], None], ...] = (
    _seed_local_media_profiles,
    _seed_notification_rules,
    _mark_background_migrations_done,
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
