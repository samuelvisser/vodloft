"""A collection's Seasons dialog: rename and order its seasons, and make its channel's playlists seasons."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app import db_session
from backend.api.models.collection_seasons import (
    CollectionSeasonsAPIRead, CollectionSeasonsAPIUpdate, CollectionListAddAPIIn, MovedEpisodesAPIRead,
    ReassignedEpisodesAPIRead,
)
from backend.db.core import run_write_transaction
from backend.security.access import Area, Level
from backend.security.deps import requires

from .service import (
    CollectionNotFoundError, link_to_add, look_up_added_link, look_up_links, links_lookup, moved_view, reassigned_view, save_added_link,
    save_listed_links, seasons_view, update_seasons,
)

router = APIRouter()


def _found(work):
    try:
        return work()
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/{collection_slug}/season-settings", dependencies=[requires(Area.LIBRARY, Level.VIEW)],
    response_model=CollectionSeasonsAPIRead,
)
def collection_seasons_get(collection_slug: str):
    """The collection's seasons in order, and whether its channel's playlists are seasons."""
    with db_session() as s:
        return _found(lambda: seasons_view(s, collection_slug))


@router.get(
    "/{collection_slug}/season-settings/moved-episodes", dependencies=[requires(Area.LIBRARY, Level.VIEW)],
    response_model=MovedEpisodesAPIRead,
)
def collection_moved_episodes_get(collection_slug: str):
    """The episodes that the collection's playlists put in another season than the one they are in."""
    with db_session() as s:
        try:
            return _found(lambda: moved_view(s, collection_slug))
        finally:
            s.rollback()


@router.get(
    "/{collection_slug}/season-settings/reassigned-episodes", dependencies=[requires(Area.LIBRARY, Level.VIEW)],
    response_model=ReassignedEpisodesAPIRead,
)
def collection_reassigned_episodes_get(collection_slug: str):
    """The downloaded episodes that the collection's channel places in another of its collections now."""
    with db_session() as s:
        try:
            return _found(lambda: reassigned_view(s, collection_slug))
        finally:
            s.rollback()


@router.put(
    "/{collection_slug}/season-settings", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CollectionSeasonsAPIRead,
)
def collection_seasons_put(collection_slug: str, body: CollectionSeasonsAPIUpdate):
    """Rename and order the collection's seasons, and set how its channel's playlists are seasons."""
    return _found(lambda: run_write_transaction(lambda s: update_seasons(s, collection_slug, body)))


@router.post(
    "/{collection_slug}/season-settings/links", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CollectionSeasonsAPIRead,
)
def link_seasons_refresh(collection_slug: str):
    """List the playlists of the collection's channel at its Site now."""
    with db_session() as s:
        lookup = _found(lambda: links_lookup(s, collection_slug))
    listing = look_up_links(lookup)
    return _found(lambda: run_write_transaction(lambda s: save_listed_links(s, collection_slug, listing)))


@router.post(
    "/{collection_slug}/season-settings/added-links", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CollectionSeasonsAPIRead,
)
def link_season_add(collection_slug: str, body: CollectionListAddAPIIn):
    """Add a playlist, channel or video as a link season of a collection that holds only what those have."""
    with db_session() as s:
        lookup = _found(lambda: link_to_add(s, collection_slug, body.url))
    link = look_up_added_link(lookup)
    return _found(lambda: run_write_transaction(lambda s: save_added_link(s, collection_slug, link)))
