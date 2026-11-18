import json
import logging
import queue
import threading
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from backend.api.models.creator import (
    CreatorAPICreate, CreatorAPIRead, CreatorAPIUpdate, CreatorCombineAPIIn, CreatorLookupAPIRead, CreatorLookupAPIRequest,
    CreatorPageAPIRead, CreatorSectionMoveAPIIn, CreatorSectionsAPIAdd,
)
from backend.api.models.collection_seasons import ReassignedMoveAPIRead
from backend.app import db_session
from backend.db.core import run_write_transaction
from backend.security.access import Access, Area, Level
from backend.security.deps import requires, signed_in
from backend.services.errors import ServiceError
from backend.services.source_requests import SourceRequestError, asking_source
from config.network import NO_INTERNET_CONNECTION_MESSAGE, is_no_internet_error

from .service import (
    CreatorNotFoundError, add_creator, add_sections, combine_creator, creator_lookup, creator_page, check_creator, list_creators,
    look_up_creator, lookup_creator_label, move_creator_reassigned, move_creator_section, update_creator,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/creators", tags=["Creators"])


@router.post(
    "/lookup", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)],
    responses={200: {"content": {"application/x-ndjson": {}}}},
)
def lookup_creator(body: CreatorLookupAPIRequest, access: Access = signed_in()):
    """Look a creator up at its Site: who it is, its sections, and what each way of adding it does with them.

    Looking a creator up can take a minute, so the answer is a line of JSON per step: first ``{"step": "...",
    "creatorLabel": "..."}`` with what the Site calls a creator, then ``{"step": "..."}`` while it
    works, then ``{"creator": CreatorLookupAPIRead}`` or ``{"error": "..."}``.
    """
    access.check_link_at(body.source_key, body.url)
    lines: queue.Queue[dict] = queue.Queue()

    def send(**line) -> None:
        lines.put(line)

    def look_up() -> None:
        try:
            label = lookup_creator_label(body.source_key, body.url)
            send(step=f"Looking the {label} up", creatorLabel=label)
            with asking_source(f"Could not look up this {label}"):
                details = look_up_creator(body.source_key, body.url, body.ref, lambda step: send(step=step))
            send(step="Checking what is in your library already")
            with db_session() as s:
                found = CreatorLookupAPIRead.model_validate(creator_lookup(s, body.source_key, details))
            send(creator=found.model_dump(mode="json", by_alias=True))
        except Exception as exc:
            if is_no_internet_error(exc):
                send(error=NO_INTERNET_CONNECTION_MESSAGE)
            elif isinstance(exc, (ServiceError, SourceRequestError)):
                send(error=str(exc))
            else:
                logger.exception("Could not look up the creator")
                send(error="Could not look up this creator")

    def stream() -> Iterator[str]:
        while True:
            line = lines.get()
            yield json.dumps(line) + "\n"
            if "step" not in line:
                return

    threading.Thread(target=look_up, name="creator-lookup", daemon=True).start()
    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=CreatorPageAPIRead, status_code=status.HTTP_201_CREATED)
def create_creator(body: CreatorAPICreate, access: Access = signed_in()):
    """Add a creator, with a collection for each place its sections go, and start indexing them."""
    access.check_link_at(body.source_key, body.url)
    with asking_source("Could not look up this creator"):
        details = look_up_creator(body.source_key, body.url, body.ref)
    return run_write_transaction(lambda s: add_creator(s, body, details, added_by_id=access.user_id))


@router.get("", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=list[CreatorAPIRead])
def creator_list():
    with db_session() as s:
        return list_creators(s)


@router.get("/{slug}", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=CreatorPageAPIRead)
def creator_get(slug: str):
    with db_session() as s:
        try:
            return creator_page(s, slug)
        except CreatorNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


def _found(work):
    try:
        return work()
    except CreatorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=CreatorPageAPIRead)
def creator_update(slug: str, body: CreatorAPIUpdate):
    """Change what happens with the creator's new sections, the genre and rating of its collections, and its order."""
    return _found(lambda: run_write_transaction(lambda s: update_creator(s, slug, body)))


@router.post(
    "/{slug}/accounts/{account_id}/sections", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)],
    response_model=CreatorPageAPIRead,
)
def creator_add_sections(slug: str, account_id: int, body: CreatorSectionsAPIAdd, access: Access = signed_in()):
    """Add sections of one of the creator's accounts to the creator's collections, or ignore them."""
    return _found(lambda: run_write_transaction(
        lambda s: add_sections(s, slug, account_id, body, added_by_id=access.user_id),
    ))


@router.post(
    "/{slug}/accounts/{account_id}/sections/{ref}/move", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CreatorPageAPIRead,
)
def creator_move_section(slug: str, account_id: int, ref: str, body: CreatorSectionMoveAPIIn, access: Access = signed_in()):
    """Move one of the playlists of a creator's account to a season of the account's own collection, to a collection
    of its own, or out of the Library, with its videos and their files."""
    return _found(lambda: run_write_transaction(
        lambda s: move_creator_section(s, slug, account_id, ref, body, added_by_id=access.user_id),
    ))


@router.post("/{slug}/combine", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=CreatorPageAPIRead)
def creator_combine(slug: str, body: CreatorCombineAPIIn):
    """Make another creator in the Library, who is the same person or group, a part of this one: their accounts and
    collections move over, and the other creator leaves the Library."""
    return _found(lambda: run_write_transaction(lambda s: combine_creator(s, slug, body)))


@router.post(
    "/{slug}/move-reassigned", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=ReassignedMoveAPIRead,
)
def creator_move_reassigned(slug: str):
    """Move every reassigned episode of the creator to the collection it belongs in now, with its files."""
    return _found(lambda: run_write_transaction(lambda s: move_creator_reassigned(s, slug)))


@router.post("/{slug}/check", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], status_code=status.HTTP_202_ACCEPTED)
def creator_check(slug: str):
    """Look for the creator's new sections now."""
    _found(lambda: run_write_transaction(lambda s: check_creator(s, slug), concurrent=True))
    return {"queued": True}
