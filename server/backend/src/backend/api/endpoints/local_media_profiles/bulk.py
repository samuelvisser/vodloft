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
from backend.api.profile_bulk import in_order, offered_changes, reason_of, skipped, summarize
from backend.db.models import LocalMediaProfileBase
from backend.services.collection_assets import request_profile_collection_assets
from backend.services.local_media_profile_sites import profile_download_options
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


def _offers(profile: LocalMediaProfileBase, name: str) -> bool:
    """Collection images are only on collection profiles, and subtitles only when one of the profile's Sites has them."""
    if name == "download_collection_assets":
        return profile.type == LocalMediaProfileType.COLLECTION.value
    if name == "subtitle_mode":
        return profile_download_options(profile.type, profile.site_keys, profile.include_upcoming_sites).subtitles
    return True


def _profiles(s: Session, ids: list[int]) -> list[LocalMediaProfileBase]:
    profile = with_polymorphic(LocalMediaProfileBase, "*")
    items = s.query(profile).filter(profile.id.in_(ids)).all()
    return in_order(ids, items, lambda item: item.id)


def summarize_local_media_profiles(s: Session, body: BulkSelectionIn) -> BulkSummaryRead:
    return summarize(_profiles(s, body.ids), LocalMediaProfileBulkChangesIn, _offers)


def change_local_media_profiles(s: Session, body: BulkChangeIn[LocalMediaProfileBulkChangesIn]) -> BulkResultRead:
    """Give the chosen profiles the same download, thumbnail, metadata, subtitle and collection image behavior.
    These only steer the next downloads and image refreshes, so nothing is moved or renamed. A profile that has
    none of the settings is skipped with why."""
    changed: list[LocalMediaProfileBase] = []
    left: list = []
    for profile in _profiles(s, body.ids):
        changes = offered_changes(body.changes, profile, _offers)
        if not changes:
            left.append(skipped(profile.id, profile.name, "It doesn't have these settings"))
            continue
        for name, value in changes.items():
            setattr(profile, name, value)
        changed.append(profile)
    s.flush()
    for profile in changed:
        if profile.type == LocalMediaProfileType.COLLECTION.value:
            request_profile_collection_assets(s, profile.id)
    return BulkResultRead(done=len(changed), skipped=left)


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
