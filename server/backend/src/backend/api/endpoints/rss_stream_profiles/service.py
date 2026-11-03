from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from backend.api.models.rss_stream_profile import (
    RssStreamProfileAPICreate,
    RssStreamProfileAPIRead,
    RssStreamProfileAPIUpdate,
)
from backend.db.model_mapping import create_database_fields, update_database_fields
from backend.db.models import Collection
from backend.db.models.stream_profile import RssStreamProfile
from backend.types.local_media_profile_types import PreferredFormat
from backend.types.stream_profile_types import RSS_HLS_OUTPUT_MODES
from backend.utils.feed_urls import build_rss_feed_url, request_base_url
from backend.security.access import Access
from backend.services.stream_profile_owners import check_owner, owned_by
from backend.utils.helpers import generate_stream_profile_token
from sources import Feature, get_source


def _title_override(title: str, collection_title: str) -> Optional[str]:
    normalized = title.strip()
    return None if normalized == collection_title else normalized


def ensure_source_can_stream(collection: Collection, use_dw_stream: bool) -> None:
    """Only a Source with RSS streaming can stream episodes that are not downloaded."""
    if not use_dw_stream:
        return
    source = get_source(collection.source_key)
    if not source.has(Feature.RSS_STREAMING):
        raise HTTPException(
            status_code=422,
            detail=f"{source.name} cannot stream episodes; a feed for this collection serves downloaded files only",
        )


def _keeps_live_episode_handoff(profile: RssStreamProfile) -> bool:
    return (
        profile.stream_live_episodes
        and profile.preferred_format != PreferredFormat.FORMAT_AUDIO_ONLY.value
        and profile.video_output_mode in RSS_HLS_OUTPUT_MODES
        and profile.use_downloads
        and not profile.use_dw_stream
    )


def get_rss_stream_profiles_list(s: Session, access: Access) -> list[RssStreamProfileAPIRead]:
    items = (
        owned_by(s.query(RssStreamProfile), RssStreamProfile.owner_user_id, access)
        .order_by(RssStreamProfile.id)
        .all()
    )
    return [RssStreamProfileAPIRead.model_validate(item) for item in items]


def get_stream_profile_rss(
        s: Session,
        access: Access,
        stream_profile_id: int,
) -> RssStreamProfileAPIRead:
    item = (
        s.query(RssStreamProfile)
        .filter_by(id=stream_profile_id)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Stream profile not found")
    check_owner(item, access)
    return RssStreamProfileAPIRead.model_validate(item)


def create_stream_profile_rss(
        s: Session,
        request: Request,
        body: RssStreamProfileAPICreate,
        access: Access,
) -> RssStreamProfileAPIRead:
    collection: Optional[Collection] = s.get(Collection, body.collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    ensure_source_can_stream(collection, body.use_dw_stream)

    token = generate_stream_profile_token()
    feed_url = (body.feed_url or "").strip() or build_rss_feed_url(
        request_base_url(request),
        token=token,
        collection_slug=collection.slug,
    )

    item = create_database_fields(
        RssStreamProfile,
        body,
        exclude_fields={"feed_url", "title"},
    )
    item.overwrite_collection_title = _title_override(body.title, collection.title)
    item.collection = collection
    item.token = token
    item.feed_url = feed_url
    item.owner_user_id = access.user_id
    s.add(item)
    s.flush()
    return RssStreamProfileAPIRead.model_validate(item)


def update_stream_profile_rss(
        s: Session,
        access: Access,
        stream_profile_id: int,
        body: RssStreamProfileAPIUpdate,
) -> RssStreamProfileAPIRead:
    item: Optional[RssStreamProfile] = (
        s.query(RssStreamProfile)
        .filter_by(id=stream_profile_id)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Stream profile not found")
    check_owner(item, access)
    ensure_source_can_stream(item.collection, body.use_dw_stream)

    feed_url = body.feed_url.strip()
    update_database_fields(item, body, exclude_fields={"feed_url", "title"})
    item.overwrite_collection_title = _title_override(body.title, item.collection.title)
    if not _keeps_live_episode_handoff(item):
        item.live_episode_handoff_ids = []
    item.feed_url = feed_url

    s.flush()
    return RssStreamProfileAPIRead.model_validate(item)


def regenerate_stream_profile_rss_token(
        s: Session,
        access: Access,
        request: Request,
        stream_profile_id: int,
) -> RssStreamProfileAPIRead:
    """Rotate a profile's secret token and invalidate its previous feed URLs.

    The new feed URL is always built on the address VODLoft was reached on, so
    regenerating also replaces an address the profile was imported with.
    """
    item: Optional[RssStreamProfile] = (
        s.query(RssStreamProfile)
        .filter_by(id=stream_profile_id)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Stream profile not found")
    check_owner(item, access)

    item.token = generate_stream_profile_token()
    item.feed_url = build_rss_feed_url(
        request_base_url(request),
        token=item.token,
        collection_slug=item.collection.slug,
    )

    s.flush()
    return RssStreamProfileAPIRead.model_validate(item)


def delete_stream_profile_rss(
        s: Session,
        access: Access,
        stream_profile_id: int,
) -> RssStreamProfileAPIRead:
    item = (
        s.query(RssStreamProfile)
        .filter_by(id=stream_profile_id)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Stream profile not found")
    check_owner(item, access)

    payload = RssStreamProfileAPIRead.model_validate(item)
    s.delete(item)
    s.flush()
    return payload
