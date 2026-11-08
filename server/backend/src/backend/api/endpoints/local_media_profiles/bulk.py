"""Bulk edit on the Local Media Profiles table."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session, with_polymorphic

from backend.api.models.profile_bulk import (
    BulkChangeIn,
    BulkResultRead,
    BulkSelectionIn,
    BulkSummaryRead,
    LocalMediaProfileBulkChangesIn,
)
from backend.api.profile_bulk import in_order, reason_of, skipped, summarize
from backend.db.models import LocalMediaProfileBase
from backend.services.collection_assets import request_profile_collection_assets
from backend.types.local_media_profile_types import LocalMediaProfileType

from ..collection_local_media_profiles.service import delete_collection_local_media_profile
from ..movie_local_media_profiles.service import delete_movie_local_media_profile
from ..video_local_media_profiles.service import delete_video_local_media_profile
from .service import ensure_local_media_profile_can_be_deleted

_DELETE = {
    LocalMediaProfileType.COLLECTION.value: delete_collection_local_media_profile,
    LocalMediaProfileType.MOVIE.value: delete_movie_local_media_profile,
    LocalMediaProfileType.VIDEO.value: delete_video_local_media_profile,
}


def _profiles(s: Session, ids: list[int]) -> list[LocalMediaProfileBase]:
    profile = with_polymorphic(LocalMediaProfileBase, "*")
    items = s.query(profile).filter(profile.id.in_(ids)).all()
    return in_order(ids, items, lambda item: item.id)


def summarize_local_media_profiles(s: Session, body: BulkSelectionIn) -> BulkSummaryRead:
    return summarize(_profiles(s, body.ids), LocalMediaProfileBulkChangesIn, lambda _profile, _name: True)


def change_local_media_profiles(s: Session, body: BulkChangeIn[LocalMediaProfileBulkChangesIn]) -> BulkResultRead:
    """Give the chosen profiles the same download, thumbnail and metadata behavior. These only steer
    the next downloads, so nothing is moved or renamed."""
    changes = {name: getattr(body.changes, name) for name in body.changes.model_fields_set}
    profiles = _profiles(s, body.ids)
    for profile in profiles:
        for name, value in changes.items():
            setattr(profile, name, value)
    s.flush()
    for profile in profiles:
        if profile.type == LocalMediaProfileType.COLLECTION.value:
            request_profile_collection_assets(s, profile.id)
    return BulkResultRead(done=len(profiles), skipped=[])


def delete_local_media_profiles(s: Session, body: BulkSelectionIn) -> BulkResultRead:
    """Delete the chosen profiles. One still in use is skipped with why."""
    done = 0
    left: list = []
    for profile in _profiles(s, body.ids):
        try:
            ensure_local_media_profile_can_be_deleted(s, profile)
        except HTTPException as error:
            left.append(skipped(profile.id, profile.name, reason_of(error)))
            continue
        _DELETE[profile.type](s, profile.slug)
        done += 1
    return BulkResultRead(done=done, skipped=left)
