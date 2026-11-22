from fastapi import APIRouter, HTTPException, Query, status

from backend.api.models.creator import (
    CreatorAPIRead, CreatorAPIUpdate, CreatorCombineAPIIn, CreatorEpisodePageAPIRead, CreatorMoviesAPIAdd,
    CreatorOfferingsAPIRead, CreatorPageAPIRead,
)
from backend.api.pagination import InvalidCursorError
from backend.app import db_session
from backend.db.core import run_write_transaction
from backend.security.access import Area, Level
from backend.security.deps import requires
from backend.services.source_requests import asking_source

from backend.api.endpoints.movies.service import look_up_movies

from .service import (
    CreatorNotFoundError, account_link, add_creator_movies, combine_creator, creator_episodes, creator_offerings,
    creator_page, delete_creator, list_creators, look_up_account, movies_to_add, offering_accounts,
    record_creator_opened, split_creator_account, update_creator,
)

router = APIRouter(prefix="/creators", tags=["Creators"])


def _found(work):
    try:
        return work()
    except CreatorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=list[CreatorAPIRead])
def creator_list():
    with db_session() as s:
        return list_creators(s)


@router.get("/{slug}", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=CreatorPageAPIRead)
def creator_get(slug: str):
    with db_session() as s:
        return _found(lambda: creator_page(s, slug))


@router.get("/{slug}/offerings", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=CreatorOfferingsAPIRead)
def creator_offerings_get(slug: str):
    """What the creator has at their Sites beside their channel, such as a Daily Wire host's shows and movies, with
    what the Library has of it. Asks each Site, so it takes a moment."""
    with db_session() as s:
        accounts = _found(lambda: offering_accounts(s, slug))
    found = [(account, look_up_account(account)) for account in accounts]
    with db_session() as s:
        try:
            return _found(lambda: creator_offerings(s, slug, found))
        finally:
            s.rollback()


@router.post(
    "/{slug}/accounts/{account_id}/movies", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)],
    response_model=CreatorPageAPIRead,
)
def creator_add_movies(slug: str, account_id: int, body: CreatorMoviesAPIAdd):
    """Add movies of one of the creator's accounts to the Library, when they aren't in it yet, and to the creator."""
    with db_session() as s:
        source_key, refs = _found(lambda: movies_to_add(s, slug, account_id, body))
    with asking_source("Could not look up the creator's movies"):
        movies = look_up_movies(source_key, refs)
    return _found(lambda: run_write_transaction(lambda s: add_creator_movies(s, slug, account_id, body, movies)))


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


@router.patch("/{slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=CreatorPageAPIRead)
def creator_update(slug: str, body: CreatorAPIUpdate):
    """Change the creator's name, and the genre and rating of their collections."""
    return _found(lambda: run_write_transaction(lambda s: update_creator(s, slug, body)))


@router.post(
    "/{slug}/accounts/{account_id}/split", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CreatorPageAPIRead,
)
def creator_split_account(slug: str, account_id: int):
    """Make one of the creator's accounts a creator of their own again, with the collections on its Site."""
    def link():
        with db_session() as s:
            return account_link(s, slug, account_id)

    details = look_up_account(_found(link))
    return _found(lambda: run_write_transaction(lambda s: split_creator_account(s, slug, account_id, details)))


@router.post("/{slug}/combine", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=CreatorPageAPIRead)
def creator_combine(slug: str, body: CreatorCombineAPIIn):
    """Make another creator in the Library, who is the same person or group, a part of this one: their accounts and
    collections move over, and the other creator leaves the Library."""
    return _found(lambda: run_write_transaction(lambda s: combine_creator(s, slug, body)))


@router.delete("/{slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], status_code=status.HTTP_204_NO_CONTENT)
def creator_delete(slug: str):
    """Take the creator out of the Library. Their collections and movies stay as they are."""
    _found(lambda: run_write_transaction(lambda s: delete_creator(s, slug)))
