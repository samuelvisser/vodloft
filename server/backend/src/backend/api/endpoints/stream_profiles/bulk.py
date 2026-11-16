"""Bulk edit on the Stream Profiles table."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session, joinedload, with_polymorphic

from backend.api.models.profile_bulk import (
    BulkChangeIn,
    BulkResultRead,
    BulkSelectionIn,
    BulkSummaryRead,
    StreamProfileBulkChangesIn,
)
from backend.api.models.iptv_stream_profile import IptvStreamProfileAPIRead, IptvStreamProfileAPIUpdate
from backend.api.models.rss_stream_profile import RssStreamProfileAPIRead, RssStreamProfileAPIUpdate
from backend.api.profile_bulk import in_order, offered_changes, reason_of, skipped, summarize
from backend.db.models.stream_profile import StreamProfileBase
from backend.security.access import Access
from backend.services.sites import collection_site
from backend.services.stream_profile_owners import owned_by
from backend.types.local_media_profile_types import PreferredFormat
from backend.types.stream_profile_types import StreamProfileType
from sources import StreamMethod

from ..iptv_stream_profiles.service import delete_stream_profile_iptv, update_stream_profile_iptv
from ..rss_stream_profiles.service import delete_stream_profile_rss, update_stream_profile_rss


@dataclass(frozen=True)
class _ProfileType:
    """How a bulk edit reads, changes and deletes a profile of one type, as its own edit page does."""

    read: type[BaseModel]
    update: type[BaseModel]
    save: Callable
    delete: Callable


_PROFILE_TYPES = {
    StreamProfileType.RSS.value: _ProfileType(
        RssStreamProfileAPIRead, RssStreamProfileAPIUpdate, update_stream_profile_rss, delete_stream_profile_rss,
    ),
    StreamProfileType.IPTV.value: _ProfileType(
        IptvStreamProfileAPIRead, IptvStreamProfileAPIUpdate, update_stream_profile_iptv, delete_stream_profile_iptv,
    ),
}


def _offers(profile: StreamProfileBase, name: str) -> bool:
    """Whether the profile has the setting, as its edit page shows it."""
    site = collection_site(profile.collection)
    video = profile.preferred_format != PreferredFormat.FORMAT_AUDIO_ONLY.value
    if name == "use_source_stream":
        return site.streams
    if name == "proxy_source_stream":
        return video and site.streams and site.stream_proxy_choice
    if name == "stream_live_episodes":
        return "hls" in profile.media_kinds and StreamMethod.LIVE in site.stream_methods
    return True


def _profiles(s: Session, access: Access, ids: list[int]) -> list[StreamProfileBase]:
    profile = with_polymorphic(StreamProfileBase, "*")
    items = (
        owned_by(s.query(profile), profile.owner_user_id, access)
        .filter(profile.id.in_(ids))
        .options(joinedload(profile.collection))
        .all()
    )
    return in_order(ids, items, lambda item: item.id)


def _name(profile: StreamProfileBase) -> str:
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
            left.append(skipped(profile.id, _name(profile), "It doesn't have these settings"))
            continue
        profile_type = _PROFILE_TYPES[profile.type]
        current = profile_type.read.model_validate(profile)
        try:
            update = profile_type.update.model_validate({
                **current.model_dump(), "title": current.effective_title, **changes,
            })
            profile_type.save(s, access, profile.id, update)
        except (HTTPException, ValidationError) as error:
            left.append(skipped(profile.id, _name(profile), reason_of(error)))
            continue
        done += 1
    return BulkResultRead(done=done, skipped=left)


def delete_stream_profiles(s: Session, access: Access, body: BulkSelectionIn) -> BulkResultRead:
    profiles = _profiles(s, access, body.ids)
    for profile in profiles:
        _PROFILE_TYPES[profile.type].delete(s, access, profile.id)
    return BulkResultRead(done=len(profiles), skipped=[])
