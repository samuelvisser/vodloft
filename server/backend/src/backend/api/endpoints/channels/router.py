from fastapi import APIRouter, HTTPException, status

from backend.api.models.channel import (
    ChannelAPICreate, ChannelAPIRead, ChannelLookupAPIRead, ChannelLookupAPIRequest, ChannelPageAPIRead,
)
from backend.app import db_session
from backend.db.core import run_write_transaction
from backend.security.access import Access, Area, Level
from backend.security.deps import requires, signed_in
from backend.services.source_requests import asking_source

from .service import ChannelNotFoundError, add_channel, channel_lookup, channel_page, list_channels, look_up_channel

router = APIRouter(prefix="/channels", tags=["Channels"])


@router.post("/lookup", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=ChannelLookupAPIRead)
def lookup_channel(body: ChannelLookupAPIRequest, access: Access = signed_in()):
    """Look a channel up at its Site: who it is, its sections, and what each way of adding it does with them."""
    access.check_link_at(body.source_key, body.url)
    with asking_source("Could not look up this channel"):
        details = look_up_channel(body.source_key, body.url, body.ref)
    with db_session() as s:
        return channel_lookup(s, body.source_key, details)


@router.post("", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=ChannelPageAPIRead, status_code=status.HTTP_201_CREATED)
def create_channel(body: ChannelAPICreate, access: Access = signed_in()):
    """Add a channel, with a collection for each place its sections go, and start indexing them."""
    access.check_link_at(body.source_key, body.url)
    with asking_source("Could not look up this channel"):
        details = look_up_channel(body.source_key, body.url, body.ref)
    return run_write_transaction(lambda s: add_channel(s, body, details, added_by_id=access.user_id))


@router.get("", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=list[ChannelAPIRead])
def channel_list():
    with db_session() as s:
        return list_channels(s)


@router.get("/{slug}", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=ChannelPageAPIRead)
def channel_get(slug: str):
    with db_session() as s:
        try:
            return channel_page(s, slug)
        except ChannelNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
