"""Bulk edit on the Download Profiles table."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from backend.api.models.profile_bulk import (
    BulkChangeIn,
    BulkResultRead,
    BulkSelectionIn,
    BulkSummaryRead,
    DownloadProfileBulkChangesIn,
)
from backend.api.profile_bulk import in_order, offered_changes, reason_of, skipped, summarize
from backend.db.models.download_profile import DownloadProfile
from backend.services.sites import collection_site, collection_site_key
from backend.types.local_media_profile_types import LocalMediaProfileType
from backend.utils.local_media_profiles import require_local_media_profile_type
from sources import SiteSetting
from task_manager.events.transactional import queue_event

from .service import _profile_event, delete_download_profile, require_one_profile_per_local_media_profile

# A setting only some Sites have; the others leave it alone.
_SITE_SETTINGS = {
    "download_with_countdown": SiteSetting.DOWNLOAD_WITH_COUNTDOWN,
    "upgrade_check": SiteSetting.UPGRADE_CHECK,
    "upgrade_repeat": SiteSetting.UPGRADE_CHECK,
    "sponsorblock_enabled": SiteSetting.SPONSORBLOCK,
}


def _offers(profile: DownloadProfile, name: str) -> bool:
    setting = _SITE_SETTINGS.get(name)
    return setting is None or collection_site(profile.collection).settings.offers(setting)


def _profiles(s: Session, ids: list[int]) -> list[DownloadProfile]:
    items = (
        s.query(DownloadProfile)
        .filter(DownloadProfile.id.in_(ids))
        .options(joinedload(DownloadProfile.collection), joinedload(DownloadProfile.local_media_profile))
        .all()
    )
    return in_order(ids, items, lambda item: item.id)


def _name(profile: DownloadProfile) -> str:
    return f"{profile.collection.title} ({profile.local_media_profile.name})"


def summarize_download_profiles(s: Session, body: BulkSelectionIn) -> BulkSummaryRead:
    return summarize(
        _profiles(s, body.ids), DownloadProfileBulkChangesIn, _offers,
        site_name=lambda profile: collection_site(profile.collection).name,
    )


def change_download_profiles(s: Session, body: BulkChangeIn[DownloadProfileBulkChangesIn]) -> BulkResultRead:
    """Give the chosen profiles the same settings. One that cannot take them is skipped with why."""
    done = 0
    left: list = []
    for profile in _profiles(s, body.ids):
        changes = offered_changes(body.changes, profile, _offers)
        if not changes:
            left.append(skipped(profile.id, _name(profile), "Its site doesn't have these settings"))
            continue
        media_profile_id = changes.get("local_media_profile_id")
        if media_profile_id is not None and media_profile_id != profile.local_media_profile_id:
            try:
                require_local_media_profile_type(
                    s, media_profile_id, LocalMediaProfileType.COLLECTION, collection_site_key(profile.collection),
                )
                require_one_profile_per_local_media_profile(
                    s, collection_id=profile.collection_id, local_media_profile_id=media_profile_id,
                    exclude_profile_id=profile.id,
                )
            except HTTPException as error:
                left.append(skipped(profile.id, _name(profile), reason_of(error)))
                continue
        for name, value in changes.items():
            setattr(profile, name, value)
        queue_event(s, "download_profile.updated", _profile_event(profile))
        done += 1
    s.flush()
    return BulkResultRead(done=done, skipped=left)


def delete_download_profiles(s: Session, body: BulkSelectionIn) -> BulkResultRead:
    profiles = _profiles(s, body.ids)
    for profile in profiles:
        delete_download_profile(s, profile.id)
    return BulkResultRead(done=len(profiles), skipped=[])
