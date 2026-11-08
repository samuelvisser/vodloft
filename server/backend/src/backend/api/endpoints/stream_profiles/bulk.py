"""Bulk edit on the Stream Profiles table."""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session, joinedload

from backend.api.models.profile_bulk import (
    BulkChangeIn,
    BulkResultRead,
    BulkSelectionIn,
    BulkSummaryRead,
    StreamProfileBulkChangesIn,
)
from backend.api.models.rss_stream_profile import RssStreamProfileAPIRead, RssStreamProfileAPIUpdate
from backend.api.profile_bulk import in_order, offered_changes, reason_of, skipped, summarize
from backend.db.models.stream_profile import RssStreamProfile
from backend.security.access import Access
from backend.services.sites import collection_site
from backend.services.stream_profile_owners import owned_by
from backend.types.local_media_profile_types import PreferredFormat
from backend.types.stream_profile_types import RSS_HLS_OUTPUT_MODES
from sources import StreamMethod

from ..rss_stream_profiles.service import delete_stream_profile_rss, update_stream_profile_rss


def _offers(profile: RssStreamProfile, name: str) -> bool:
    """Whether the profile's feed has the setting, as its edit page shows it."""
    site = collection_site(profile.collection)
    video = profile.preferred_format != PreferredFormat.FORMAT_AUDIO_ONLY.value
    if name == "use_source_stream":
        return site.streams
    if name == "proxy_source_stream":
        return video and site.streams and site.stream_proxy_choice
    if name == "stream_live_episodes":
        return video and profile.video_output_mode in RSS_HLS_OUTPUT_MODES and StreamMethod.LIVE in site.stream_methods
    return True


def _profiles(s: Session, access: Access, ids: list[int]) -> list[RssStreamProfile]:
    items = (
        owned_by(s.query(RssStreamProfile), RssStreamProfile.owner_user_id, access)
        .filter(RssStreamProfile.id.in_(ids))
        .options(joinedload(RssStreamProfile.collection))
        .all()
    )
    return in_order(ids, items, lambda item: item.id)


def _name(profile: RssStreamProfile) -> str:
    return profile.overwrite_collection_title or profile.collection.title


def summarize_stream_profiles(s: Session, access: Access, body: BulkSelectionIn) -> BulkSummaryRead:
    return summarize(_profiles(s, access, body.ids), StreamProfileBulkChangesIn, _offers)


def change_stream_profiles(
        s: Session, access: Access, body: BulkChangeIn[StreamProfileBulkChangesIn],
) -> BulkResultRead:
    """Give the chosen feeds the same settings, checked as their edit page checks them. One that
    cannot take them is skipped with why."""
    done = 0
    left: list = []
    for profile in _profiles(s, access, body.ids):
        changes = offered_changes(body.changes, profile, _offers)
        if not changes:
            left.append(skipped(profile.id, _name(profile), "Its feed doesn't have these settings"))
            continue
        current = RssStreamProfileAPIRead.model_validate(profile)
        try:
            update = RssStreamProfileAPIUpdate.model_validate({
                **current.model_dump(), "title": current.effective_title, **changes,
            })
            update_stream_profile_rss(s, access, profile.id, update)
        except (HTTPException, ValidationError) as error:
            left.append(skipped(profile.id, _name(profile), reason_of(error)))
            continue
        done += 1
    return BulkResultRead(done=done, skipped=left)


def delete_stream_profiles(s: Session, access: Access, body: BulkSelectionIn) -> BulkResultRead:
    profiles = _profiles(s, access, body.ids)
    for profile in profiles:
        delete_stream_profile_rss(s, access, profile.id)
    return BulkResultRead(done=len(profiles), skipped=[])
