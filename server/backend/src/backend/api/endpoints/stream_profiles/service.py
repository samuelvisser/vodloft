from __future__ import annotations
from backend.security.access import Access
from backend.services.stream_profile_owners import check_owner, owned_by

from typing import Optional, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session, with_polymorphic
from fastapi import HTTPException

from backend.api.models.stream_profile import StreamAccessRead, StreamProfileAPIRead
from backend.db.model_mapping import create_database_fields, update_database_fields
from backend.db.models import Collection, StreamProfileBase
from backend.services.stream_tokens import stream_token_holder
from backend.services.sites import collection_site
from backend.utils.helpers import generate_stream_profile_token
from backend.services.stream_episodes import keeps_live_episode_handoff
from backend.types.local_media_profile_types import PREFERRED_FORMAT_HEIGHTS, PreferredFormat
from backend.types.stream_profile_types import RSS_HLS_OUTPUT_MODES
from sources import StreamMethod

Profile = TypeVar("Profile", bound=StreamProfileBase)


def get_stream_profiles_list(s: Session, access: Access, collection_slug: Optional[str] = None) -> list[StreamProfileAPIRead]:
    SP = with_polymorphic(StreamProfileBase, "*")
    if collection_slug is not None:
        items = (
            owned_by(s.query(SP), SP.owner_user_id, access)
            .filter(
                SP.collection.has(slug=collection_slug)
            )
            .order_by(SP.id.asc())
            .all()
        )
    else:
        items = (
            owned_by(s.query(SP), SP.owner_user_id, access)
            .order_by(SP.id.asc())
            .all()
        )
    return [StreamProfileAPIRead.model_validate(it) for it in items]


def get_stream_profile(s: Session, access: Access, stream_profile_id: int) -> StreamProfileAPIRead:
    SP = with_polymorphic(StreamProfileBase, "*")
    item: Optional[SP] = (
        s.query(SP)
        .filter_by(id=stream_profile_id)
        .one_or_none()
    )

    if item is None:
        raise HTTPException(status_code=404, detail="Stream profile not found")
    check_owner(item, access)

    return StreamProfileAPIRead.model_validate(item)


def title_override(title: str, collection_title: str) -> Optional[str]:
    """What a profile stores of its title: nothing when it is the collection's own."""
    normalized = title.strip()
    return None if normalized == collection_title else normalized


def ensure_site_can_stream(
        collection: Collection, *, use_source_stream: bool, stream_live_episodes: bool,
        preferred_format: str, video_output_mode: Optional[str],
) -> None:
    """A feed only streams episodes that are not downloaded in a way the collection's Site offers:
    as files, as HLS video, and live. HLS video also needs the Site to stream it or keep it as a download."""
    site = collection_site(collection)
    if use_source_stream and not site.streams:
        raise HTTPException(
            status_code=422,
            detail=f"{site.name} cannot stream episodes; a feed for this collection serves downloaded files only",
        )
    hls_video = (
        preferred_format != PreferredFormat.FORMAT_AUDIO_ONLY.value and video_output_mode in RSS_HLS_OUTPUT_MODES
    )
    # HLS video comes from the Site's stream or from downloads kept as an HLS bundle.
    if hls_video and StreamMethod.HLS not in site.stream_methods and not site.downloads.hls_bundle:
        raise HTTPException(status_code=422, detail=f"{site.name} has no HLS video; choose an MP4 video output")
    if stream_live_episodes and StreamMethod.LIVE not in site.stream_methods:
        raise HTTPException(status_code=422, detail=f"{site.name} cannot stream live episodes")
    # A feed serves the downloaded version nearest to its format, or the Site's own stream, which only
    # comes in the resolutions the Site streams.
    height = PREFERRED_FORMAT_HEIGHTS.get(preferred_format)
    heights = set(site.stream_video_heights if use_source_stream and site.stream_video_heights else site.downloads.video_heights)
    if height is not None and height not in heights:
        raise HTTPException(status_code=422, detail=f"{site.name} has no {preferred_format.removeprefix('format_')} video")


def get_stream_access(s: Session, access: Access) -> StreamAccessRead:
    return StreamAccessRead.model_validate(stream_token_holder(s, access.user_id))


def regenerate_stream_access(s: Session, access: Access) -> StreamAccessRead:
    """Rotate the user's stream token, so the previous playlist and guide addresses stop working."""
    holder = stream_token_holder(s, access.user_id)
    holder.stream_token = generate_stream_profile_token()
    s.flush()
    return StreamAccessRead.model_validate(holder)


def owned_profile(s: Session, access: Access, model: type[Profile], stream_profile_id: int) -> Profile:
    """The stream profile of this type, when the user may change it."""
    item = s.query(model).filter_by(id=stream_profile_id).one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Stream profile not found")
    check_owner(item, access)
    return item


def new_profile(
        s: Session, access: Access, model: type[Profile], body: BaseModel, *,
        exclude_fields: frozenset[str] = frozenset(), video_output_mode: Optional[str] = None,
) -> Profile:
    """A new stream profile of this type for the body's collection, with a token of its own, owned by the user."""
    collection: Optional[Collection] = s.get(Collection, body.collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    ensure_site_can_stream(
        collection, use_source_stream=body.use_source_stream, stream_live_episodes=body.stream_live_episodes,
        preferred_format=body.preferred_format, video_output_mode=video_output_mode,
    )
    item = create_database_fields(model, body, exclude_fields={"title", *exclude_fields})
    item.overwrite_collection_title = title_override(body.title, collection.title)
    item.collection = collection
    item.token = generate_stream_profile_token()
    item.owner_user_id = access.user_id
    s.add(item)
    return item


def change_profile(
        item: StreamProfileBase, body: BaseModel, *,
        exclude_fields: frozenset[str] = frozenset(), video_output_mode: Optional[str] = None,
) -> None:
    """Give a stream profile the body's settings, as its edit page saves them."""
    ensure_site_can_stream(
        item.collection, use_source_stream=body.use_source_stream, stream_live_episodes=body.stream_live_episodes,
        preferred_format=body.preferred_format, video_output_mode=video_output_mode,
    )
    update_database_fields(item, body, exclude_fields={"title", *exclude_fields})
    item.overwrite_collection_title = title_override(body.title, item.collection.title)
    if not keeps_live_episode_handoff(item):
        item.live_episode_handoff_ids = []
