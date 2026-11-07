from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.services import local_media_profile_changes as profile_changes
from backend.api.endpoints.local_media_profiles.service import delete_local_media_profile_record
from backend.api.models.movie_local_media_profile import (
    MovieLocalMediaProfileAPICreate,
    MovieLocalMediaProfileAPIRead,
    MovieLocalMediaProfileAPIUpdate,
)
from backend.db.models import MovieLocalMediaProfile


def get_movie_local_media_profiles_list(
    s: Session,
) -> list[MovieLocalMediaProfileAPIRead]:
    items = (
        s.query(MovieLocalMediaProfile)
        .order_by(MovieLocalMediaProfile.id)
        .all()
    )
    return [MovieLocalMediaProfileAPIRead.model_validate(item) for item in items]


def get_movie_local_media_profile(
    s: Session,
    local_media_profile_slug: str,
) -> MovieLocalMediaProfileAPIRead:
    item: Optional[MovieLocalMediaProfile] = (
        s.query(MovieLocalMediaProfile)
        .filter_by(slug=local_media_profile_slug)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Movie Local Media Profile not found")
    return MovieLocalMediaProfileAPIRead.model_validate(item)


def create_movie_local_media_profile(
    s: Session,
    body: MovieLocalMediaProfileAPICreate,
) -> MovieLocalMediaProfileAPIRead:
    return MovieLocalMediaProfileAPIRead.model_validate(profile_changes.create_movie_local_media_profile(s, body))


def update_movie_local_media_profile(
    s: Session,
    local_media_profile_slug: str,
    body: MovieLocalMediaProfileAPIUpdate,
) -> MovieLocalMediaProfileAPIRead:
    return MovieLocalMediaProfileAPIRead.model_validate(
        profile_changes.update_movie_local_media_profile(s, local_media_profile_slug, body),
    )


def delete_movie_local_media_profile(
    s: Session,
    local_media_profile_slug: str,
) -> MovieLocalMediaProfileAPIRead:
    item: Optional[MovieLocalMediaProfile] = (
        s.query(MovieLocalMediaProfile)
        .filter_by(slug=local_media_profile_slug)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Movie Local Media Profile not found")

    payload = MovieLocalMediaProfileAPIRead.model_validate(item)
    delete_local_media_profile_record(s, item)
    return payload
