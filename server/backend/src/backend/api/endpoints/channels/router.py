import json
import logging
import queue
import threading
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from backend.api.models.channel import (
    ChannelAPICreate, ChannelAPIRead, ChannelAPIUpdate, ChannelLookupAPIRead, ChannelLookupAPIRequest, ChannelPageAPIRead,
    ChannelSectionsAPIAdd,
)
from backend.app import db_session
from backend.db.core import run_write_transaction
from backend.security.access import Access, Area, Level
from backend.security.deps import requires, signed_in
from backend.services.errors import ServiceError
from backend.services.source_requests import SourceRequestError, asking_source
from config.network import NO_INTERNET_CONNECTION_MESSAGE, is_no_internet_error

from .service import (
    ChannelNotFoundError, add_channel, add_sections, channel_lookup, channel_page, check_channel, list_channels, look_up_channel,
    update_channel,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["Channels"])


@router.post(
    "/lookup", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)],
    responses={200: {"content": {"application/x-ndjson": {}}}},
)
def lookup_channel(body: ChannelLookupAPIRequest, access: Access = signed_in()):
    """Look a channel up at its Site: who it is, its sections, and what each way of adding it does with them.

    Looking a channel up can take a minute, so the answer is a line of JSON per step: ``{"step": "..."}`` while it
    works, then ``{"channel": ChannelLookupAPIRead}`` or ``{"error": "..."}``.
    """
    access.check_link_at(body.source_key, body.url)
    lines: queue.Queue[dict] = queue.Queue()

    def send(**line) -> None:
        lines.put(line)

    def look_up() -> None:
        try:
            with asking_source("Could not look up this channel"):
                details = look_up_channel(body.source_key, body.url, body.ref, lambda step: send(step=step))
            send(step="Checking what is in your library already")
            with db_session() as s:
                found = ChannelLookupAPIRead.model_validate(channel_lookup(s, body.source_key, details))
            send(channel=found.model_dump(mode="json", by_alias=True))
        except Exception as exc:
            if is_no_internet_error(exc):
                send(error=NO_INTERNET_CONNECTION_MESSAGE)
            elif isinstance(exc, (ServiceError, SourceRequestError)):
                send(error=str(exc))
            else:
                logger.exception("Could not look up the channel")
                send(error="Could not look up this channel")

    def stream() -> Iterator[str]:
        while True:
            line = lines.get()
            yield json.dumps(line) + "\n"
            if "step" not in line:
                return

    threading.Thread(target=look_up, name="channel-lookup", daemon=True).start()
    return StreamingResponse(stream(), media_type="application/x-ndjson")


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


def _found(work):
    try:
        return work()
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=ChannelPageAPIRead)
def channel_update(slug: str, body: ChannelAPIUpdate):
    """Change what happens with the channel's new sections, the genre and rating of its collections, and its order."""
    return _found(lambda: run_write_transaction(lambda s: update_channel(s, slug, body)))


@router.post("/{slug}/sections", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=ChannelPageAPIRead)
def channel_add_sections(slug: str, body: ChannelSectionsAPIAdd, access: Access = signed_in()):
    """Add sections of the channel to its collections, or ignore them."""
    return _found(lambda: run_write_transaction(lambda s: add_sections(s, slug, body, added_by_id=access.user_id)))


@router.post("/{slug}/check", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], status_code=status.HTTP_202_ACCEPTED)
def channel_check(slug: str):
    """Look for the channel's new sections now."""
    _found(lambda: run_write_transaction(lambda s: check_channel(s, slug), concurrent=True))
    return {"queued": True}
