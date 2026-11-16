from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.api.models.iptv_stream_profile import (
    IptvStreamProfileAPICreate,
    IptvStreamProfileAPIRead,
    IptvStreamProfileAPIUpdate,
)
from backend.db.model_mapping import create_database_fields, update_database_fields
from backend.db.models import Collection
from backend.db.models.stream_profile import IptvStreamProfile
from backend.security.access import Access
from backend.services.iptv import next_channel_number
from backend.services.stream_episodes import keeps_live_episode_handoff
from backend.services.stream_profile_owners import check_owner, owned_by
from backend.utils.helpers import generate_stream_profile_token
from ..stream_profiles.service import ensure_site_can_stream, title_override


def _profile(s: Session, access: Access, stream_profile_id: int) -> IptvStreamProfile:
    item = s.query(IptvStreamProfile).filter_by(id=stream_profile_id).one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Stream profile not found")
    check_owner(item, access)
    return item


def get_iptv_stream_profiles_list(s: Session, access: Access) -> list[IptvStreamProfileAPIRead]:
    items = (
        owned_by(s.query(IptvStreamProfile), IptvStreamProfile.owner_user_id, access)
        .order_by(IptvStreamProfile.channel_number, IptvStreamProfile.id)
        .all()
    )
    return [IptvStreamProfileAPIRead.model_validate(item) for item in items]


def get_stream_profile_iptv(s: Session, access: Access, stream_profile_id: int) -> IptvStreamProfileAPIRead:
    return IptvStreamProfileAPIRead.model_validate(_profile(s, access, stream_profile_id))


def get_next_channel_number(s: Session, access: Access) -> int:
    return next_channel_number(s, access.user_id)


def create_stream_profile_iptv(
        s: Session,
        body: IptvStreamProfileAPICreate,
        access: Access,
) -> IptvStreamProfileAPIRead:
    collection: Optional[Collection] = s.get(Collection, body.collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    ensure_site_can_stream(
        collection, use_source_stream=body.use_source_stream, stream_live_episodes=body.stream_live_episodes,
        preferred_format=body.preferred_format, video_output_mode=None,
    )

    item = create_database_fields(IptvStreamProfile, body, exclude_fields={"title", "channel_number"})
    item.overwrite_collection_title = title_override(body.title, collection.title)
    item.collection = collection
    item.token = generate_stream_profile_token()
    item.owner_user_id = access.user_id
    item.channel_number = body.channel_number or next_channel_number(s, access.user_id)
    s.add(item)
    s.flush()
    return IptvStreamProfileAPIRead.model_validate(item)


def update_stream_profile_iptv(
        s: Session,
        access: Access,
        stream_profile_id: int,
        body: IptvStreamProfileAPIUpdate,
) -> IptvStreamProfileAPIRead:
    item = _profile(s, access, stream_profile_id)
    ensure_site_can_stream(
        item.collection, use_source_stream=body.use_source_stream, stream_live_episodes=body.stream_live_episodes,
        preferred_format=body.preferred_format, video_output_mode=None,
    )

    update_database_fields(item, body, exclude_fields={"title", "channel_number"})
    item.overwrite_collection_title = title_override(body.title, item.collection.title)
    if body.channel_number is not None:
        item.channel_number = body.channel_number
    if not keeps_live_episode_handoff(item):
        item.live_episode_handoff_ids = []
    s.flush()
    return IptvStreamProfileAPIRead.model_validate(item)


def regenerate_stream_profile_iptv_token(s: Session, access: Access, stream_profile_id: int) -> IptvStreamProfileAPIRead:
    """Rotate the channel's secret token, so its previous playlist, guide and channel addresses stop working."""
    item = _profile(s, access, stream_profile_id)
    item.token = generate_stream_profile_token()
    s.flush()
    return IptvStreamProfileAPIRead.model_validate(item)


def delete_stream_profile_iptv(s: Session, access: Access, stream_profile_id: int) -> IptvStreamProfileAPIRead:
    item = _profile(s, access, stream_profile_id)
    payload = IptvStreamProfileAPIRead.model_validate(item)
    s.delete(item)
    s.flush()
    return payload
