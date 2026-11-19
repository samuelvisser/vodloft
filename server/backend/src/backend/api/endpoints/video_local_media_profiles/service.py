from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.services import local_media_profile_changes as profile_changes
from backend.api.endpoints.local_media_profiles.service import delete_local_media_profile_record
from backend.api.models.video_local_media_profile import (
    VideoLocalMediaProfileAPICreate,
    VideoLocalMediaProfileAPIRead,
    VideoLocalMediaProfileAPIUpdate,
)
from backend.db.models import VideoLocalMediaProfile


def get_video_local_media_profiles_list(
    s: Session,
) -> list[VideoLocalMediaProfileAPIRead]:
    items = (
        s.query(VideoLocalMediaProfile)
        .order_by(VideoLocalMediaProfile.id)
        .all()
    )
    return [VideoLocalMediaProfileAPIRead.model_validate(item) for item in items]


def get_video_local_media_profile(
    s: Session,
    local_media_profile_slug: str,
) -> VideoLocalMediaProfileAPIRead:
    item: Optional[VideoLocalMediaProfile] = (
        s.query(VideoLocalMediaProfile)
        .filter_by(slug=local_media_profile_slug)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Video Local Media Profile not found")
    return VideoLocalMediaProfileAPIRead.model_validate(item)


def create_video_local_media_profile(
    s: Session,
    body: VideoLocalMediaProfileAPICreate,
) -> VideoLocalMediaProfileAPIRead:
    return VideoLocalMediaProfileAPIRead.model_validate(profile_changes.create_video_local_media_profile(s, body))


def update_video_local_media_profile(
    s: Session,
    local_media_profile_slug: str,
    body: VideoLocalMediaProfileAPIUpdate,
) -> VideoLocalMediaProfileAPIRead:
    return VideoLocalMediaProfileAPIRead.model_validate(
        profile_changes.update_video_local_media_profile(s, local_media_profile_slug, body),
    )


def delete_video_local_media_profile(
    s: Session,
    local_media_profile_slug: str,
) -> VideoLocalMediaProfileAPIRead:
    item: Optional[VideoLocalMediaProfile] = (
        s.query(VideoLocalMediaProfile)
        .filter_by(slug=local_media_profile_slug)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Video Local Media Profile not found")

    payload = VideoLocalMediaProfileAPIRead.model_validate(item)
    delete_local_media_profile_record(s, item)
    return payload
