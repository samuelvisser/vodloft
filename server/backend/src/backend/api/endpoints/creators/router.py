from fastapi import APIRouter, HTTPException, Query, status

from backend.api.models.creator import (
    CreatorAPICreate, CreatorAPIRead, CreatorAPIUpdate, CreatorCombineAPIIn, CreatorLookupAPIRead, CreatorLookupAPIRequest,
    CreatorEpisodePageAPIRead, CreatorPageAPIRead, CreatorSectionMovesAPIIn, CreatorSectionMovesPreviewAPIRead, ReconcileAPIIn, ReconcileAPIRead,
    CreatorSectionsAPIAdd,
    CreatorSectionsAPIShow,
)
from backend.api.pagination import InvalidCursorError
from backend.api.endpoints.reconcile import creator_scope, move, preview_move
from backend.api.models.source import NamesAPIRead
from backend.api.steps import STEPS_RESPONSE, stream_steps
from backend.app import db_session
from backend.db.core import run_write_transaction
from backend.security.access import Access, Area, Level
from backend.security.deps import requires, signed_in
from backend.services.source_requests import asking_source

from backend.api.endpoints.movies.service import look_up_movies

from . import lookups
from .bulk import delete_creators
from backend.api.models.profile_bulk import BulkResultRead, BulkSelectionIn
from .service import (
    CreatorNotFoundError, account_link, account_movies_to_add, creator_movies_to_add, creator_episodes, add_creator, add_sections, combine_creator, look_up_account, split_creator_account, creator_lookup, creator_page, check_creator, delete_creator, list_creators,
    list_skipped_moved, look_up_creator, lookup_creator_names, record_creator_opened, preview_creator_moves, show_sections, update_creator,
)

router = APIRouter(prefix="/creators", tags=["Creators"])


@router.post("/lookup", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], responses=STEPS_RESPONSE)
def lookup_creator(body: CreatorLookupAPIRequest, access: Access = signed_in()):
    """Look a creator up at its Site: who it is, its sections, and what each way of adding it does with them.

    Looking a creator up can take a minute, so the answer is a line of JSON per step: first ``{"step": "...",
    "creatorNames": {"one", "many", "a"}}`` with what the Site calls a creator, then ``{"step": "..."}`` while it
    works, then ``{"creator": CreatorLookupAPIRead}`` or ``{"error": "..."}``.
    """
    access.check_link_at(body.source_key, body.url)

    def look_up(send) -> dict:
        names = lookup_creator_names(body.source_key, body.url)
        send(step=f"Looking the {names.singular} up", creatorNames=NamesAPIRead.model_validate(names).model_dump(mode="json"))
        with asking_source(f"Could not look up this {names.singular}"):
            details = look_up_creator(body.source_key, body.url, body.ref, lambda step: send(step=step))
        send(step="Checking what is in your library already")
        with db_session() as s:
            found = CreatorLookupAPIRead.model_validate(creator_lookup(s, body.source_key, details))
        found.lookup_id = lookups.keep(("creator", body.source_key, body.url, body.ref), details)
        return {"creator": found.model_dump(mode="json", by_alias=True)}

    return stream_steps(look_up, "Could not look up this creator")


@router.post("/bulk/delete", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=BulkResultRead)
def creators_bulk_delete(body: BulkSelectionIn):
    """Take the chosen creators out of the Library. Their collections stay, with their episodes and files."""
    return run_write_transaction(lambda s: delete_creators(s, body))


@router.post("", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=CreatorPageAPIRead, status_code=status.HTTP_201_CREATED)
def create_creator(body: CreatorAPICreate, access: Access = signed_in()):
    """Add a creator, with a collection for each place its sections go, and start indexing them."""
    access.check_link_at(body.source_key, body.url)
    details = lookups.found(body.lookup_id, ("creator", body.source_key, body.url, body.ref))
    if details is None:
        with asking_source("Could not look up this creator"):
            details = look_up_creator(body.source_key, body.url, body.ref)
    with asking_source("Could not look up this creator's movies"):
        movies = look_up_movies(body.source_key, creator_movies_to_add(body, details))
    return run_write_transaction(lambda s: add_creator(s, body, details, added_by_id=access.user_id, movies=movies))


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


@router.post("/{slug}/opened", dependencies=[requires(Area.LIBRARY, Level.VIEW)], status_code=status.HTTP_204_NO_CONTENT)
def creator_opened(slug: str) -> None:
    """Count that someone opened the creator's page, so the Library can list the most used creators first."""
    _found(lambda: run_write_transaction(lambda s: record_creator_opened(s, slug), concurrent=True))


@router.get("/{slug}/episodes", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=CreatorEpisodePageAPIRead)
def creator_episode_page(
        slug: str,
        cursor: str | None = Query(default=None, max_length=2048),
        limit: int = Query(default=12, ge=1, le=100),
):
    """One page of the episodes of all of the creator's collections, newest first, for the row on their page."""
    with db_session() as s:
        try:
            return creator_episodes(s, slug, cursor=cursor, limit=limit)
        except CreatorNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (InvalidCursorError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


def _found(work):
    try:
        return work()
    except CreatorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=CreatorPageAPIRead)
def creator_update(slug: str, body: CreatorAPIUpdate, access: Access = signed_in()):
    """Change what happens with the creator's new sections, the genre and rating of its collections, and where its
    feeds and lists go: those move with their videos, after which each collection that changed numbers its episodes
    again, renames its files and rewrites their metadata."""
    listed = _found(lambda: list_skipped_moved(slug, body))
    return _found(lambda: run_write_transaction(lambda s: update_creator(s, slug, body, added_by_id=access.user_id, listed=listed)))


@router.post(
    "/{slug}/accounts/{account_id}/sections", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)],
    response_model=CreatorPageAPIRead,
)
def creator_add_sections(slug: str, account_id: int, body: CreatorSectionsAPIAdd, access: Access = signed_in()):
    """Add sections of one of the creator's accounts to the creator's collections, or ignore them. A movie of the
    account goes into the Library, when it isn't there yet, and joins the creator."""
    def add():
        source_key, refs = account_movies_to_add(slug, account_id, body)
        with asking_source("Could not look up the creator's movies"):
            movies = look_up_movies(source_key, refs)
        return run_write_transaction(
            lambda s: add_sections(s, slug, account_id, body, added_by_id=access.user_id, movies=movies),
        )

    return _found(add)


@router.post(
    "/{slug}/accounts/{account_id}/sections/show", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)],
    response_model=CreatorPageAPIRead,
)
def creator_show_sections(slug: str, account_id: int, body: CreatorSectionsAPIShow):
    """Show sections of one of the creator's accounts that were hidden on the creator page there again."""
    return _found(lambda: run_write_transaction(lambda s: show_sections(s, slug, account_id, body), concurrent=True))


@router.post(
    "/{slug}/moves/preview", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CreatorSectionMovesPreviewAPIRead,
)
def creator_preview_moves(slug: str, body: CreatorSectionMovesAPIIn):
    """What moving feeds and lists of the creator elsewhere does to each of its collections: the videos that move or
    leave the Library, the downloads deleted, the files renamed, and the episodes that get a new number. Changes
    nothing: saving the creator with these moves makes them."""
    # A skipped list that moves takes its videos along, so the move asks its Site what it has first.
    listed = _found(lambda: list_skipped_moved(slug, body))
    return _found(lambda: run_write_transaction(lambda s: preview_creator_moves(s, slug, body, listed)))


@router.post(
    "/{slug}/accounts/{account_id}/split", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CreatorPageAPIRead,
)
def creator_split_account(slug: str, account_id: int):
    """Make one of the creator's accounts a creator of their own again, with the collections it keeps."""
    def link():
        with db_session() as s:
            return account_link(s, slug, account_id)

    source_key, ref = _found(link)
    details = look_up_account(source_key, ref)
    return _found(lambda: run_write_transaction(lambda s: split_creator_account(s, slug, account_id, details)))


@router.post("/{slug}/combine", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=CreatorPageAPIRead)
def creator_combine(slug: str, body: CreatorCombineAPIIn):
    """Make another creator in the Library, who is the same person or group, a part of this one: their accounts and
    collections move over, and the other creator leaves the Library."""
    return _found(lambda: run_write_transaction(lambda s: combine_creator(s, slug, body)))


@router.post(
    "/{slug}/reconcile/preview", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CreatorSectionMovesPreviewAPIRead,
)
def creator_reconcile_preview(slug: str):
    """What moving the creator's Reassigned and Moved episodes to where they belong now does to each of its
    collections. Changes nothing."""
    return run_write_transaction(lambda s: preview_move(s, creator_scope(slug)))


@router.post("/{slug}/reconcile", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=ReconcileAPIRead)
def creator_reconcile(slug: str, body: ReconcileAPIIn):
    """Move the creator's Reassigned and Moved episodes, with their files, to where they belong now."""
    return run_write_transaction(lambda s: move(s, creator_scope(slug), body))


@router.delete("/{slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], status_code=status.HTTP_204_NO_CONTENT)
def creator_delete(slug: str):
    """Take the creator out of the Library. Its collections stay, with their episodes and files, as plain collections."""
    _found(lambda: run_write_transaction(lambda s: delete_creator(s, slug)))


@router.post("/{slug}/check", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], status_code=status.HTTP_202_ACCEPTED)
def creator_check(slug: str):
    """Look for the creator's new sections now."""
    _found(lambda: run_write_transaction(lambda s: check_creator(s, slug), concurrent=True))
    return {"queued": True}
