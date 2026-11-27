"""A collection's Seasons dialog: rename and order its seasons, choose its channel's feeds, and make the channel's
playlists seasons."""
from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, HTTPException, Query

from backend.app import db_session
from backend.api.models.collection_seasons import (
    AddedLinkAPIRead, CollectionSeasonsAPIRead, CollectionSeasonsAPIUpdate, CollectionListAddAPIIn, MovedEpisodesAPIRead,
    SeasonsListingAPIRead, SeasonsListingsAPIIn, SeasonsListingsAPIRead, SeasonsPreviewAPIRead, SeasonsReviewAPIRead,
    SeasonsSavingAPIRead,
    TOKEN_PATTERN,
)
from backend.db.core import run_write_transaction
from backend.security.access import Area, Level
from backend.security.deps import requires
from backend.services.list_previews import (
    forget_listings, kept_for_dialog, listings, newest_review, saving, saving_plan, start_listings,
)

from .service import (
    CollectionNotFoundError, Listed, check_added_link, plan_step, saving_steps, link_to_add, lists_to_list, look_up_added_link, look_up_links,
    links_lookup, moved_view, preview_seasons, review_seasons, save_listed_links, seasons_view, update_seasons,
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
    """The collection's seasons in order, and which feeds it takes, and whether its channel's playlists are seasons."""
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


@router.put(
    "/{collection_slug}/season-settings", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CollectionSeasonsAPIRead,
)
def collection_seasons_put(collection_slug: str, body: CollectionSeasonsAPIUpdate):
    """Save the Seasons dialog as its review showed it: rename and order the collection's seasons, choose its
    channel's feeds, set how its lists are seasons, and move the downloads that belong in another season then. The
    links the user adds are looked up first, outside the write."""
    listed = _listed(collection_slug, body.listing_token)
    with db_session() as s:
        steps = _found(lambda: saving_steps(s, collection_slug, body, listed))
    # The dialog follows how far the save is by its token (``collection_seasons_saving``).
    plan = saving_plan(collection_slug, body.listing_token, steps)
    with plan_step(plan, "look_up"):
        added = [
            replace(_look_up(collection_slug, link.url), as_season=link.as_season, items=listed.links.get(link.url, ()))
            for link in body.added_links
        ]
    return _found(lambda: run_write_transaction(lambda s: update_seasons(s, collection_slug, body, added, listed, plan)))


@router.get(
    "/{collection_slug}/season-settings/saving", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=SeasonsSavingAPIRead,
)
def collection_seasons_saving(collection_slug: str, token: str = Query(min_length=8, max_length=64, pattern=TOKEN_PATTERN)):
    """How far the save of the open Seasons dialog, or of the Library's bulk edit, is: the steps of its plan."""
    return SeasonsSavingAPIRead(plan=saving(collection_slug, token))


def _listed(collection_slug: str, token: str | None) -> Listed:
    return Listed.of(listings(collection_slug, token))


def _look_up(collection_slug: str, url: str):
    with db_session() as s:
        lookup = _found(lambda: link_to_add(s, collection_slug, url))
    return look_up_added_link(lookup)


@router.post(
    "/{collection_slug}/season-settings/preview", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=SeasonsPreviewAPIRead,
)
def collection_seasons_preview(collection_slug: str, body: CollectionSeasonsAPIUpdate):
    """The seasons saving the Seasons dialog with these settings would leave. Nothing is saved."""
    listed = _listed(collection_slug, body.listing_token)
    with db_session() as s:
        try:
            return _found(lambda: preview_seasons(s, collection_slug, body, listed, kept_for_dialog(collection_slug, body.listing_token)))
        finally:
            s.rollback()


@router.post(
    "/{collection_slug}/season-settings/review", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=SeasonsReviewAPIRead,
)
def collection_seasons_review(collection_slug: str, body: CollectionSeasonsAPIUpdate):
    """What saving the Seasons dialog with these settings does: what moves, what leaves, what gets deleted. The user
    agrees to it before saving. Nothing is saved."""
    # The dialog asks again for each change: an older review it still runs stops.
    wanted = newest_review(collection_slug, body.listing_token)
    listed = _listed(collection_slug, body.listing_token)
    with db_session() as s:
        try:
            return _found(lambda: review_seasons(
                s, collection_slug, body, listed, wanted, kept_for_dialog(collection_slug, body.listing_token),
            ))
        finally:
            s.rollback()


@router.post(
    "/{collection_slug}/season-settings/listings", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=SeasonsListingsAPIRead,
)
def collection_seasons_listings(collection_slug: str, body: SeasonsListingsAPIIn):
    """List these lists of the collection, and these links the user adds, in the background for the open Seasons
    dialog's review, unless it listed them already; and say how far each of its listings is."""
    with db_session() as s:
        try:
            wanted = _found(lambda: lists_to_list(s, collection_slug, body))
        finally:
            s.rollback()
    start_listings(collection_slug, body.token, wanted)
    return SeasonsListingsAPIRead(listings=[
        SeasonsListingAPIRead.model_validate(listing) for listing in listings(collection_slug, body.token)
    ])


@router.delete(
    "/{collection_slug}/season-settings/listings", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], status_code=204,
)
def collection_seasons_listings_forget(
    collection_slug: str, token: str = Query(min_length=8, max_length=64, pattern=TOKEN_PATTERN),
):
    """The Seasons dialog closed: forget what it listed."""
    forget_listings(collection_slug, token)


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
    response_model=AddedLinkAPIRead,
)
def link_season_add(collection_slug: str, body: CollectionListAddAPIIn):
    """Look up a playlist, channel or video the user adds as a link season of a collection that holds only what those
    have. Nothing is saved: the Seasons dialog saves it with the rest."""
    link = _look_up(collection_slug, body.url)
    with db_session() as s:
        try:
            return AddedLinkAPIRead.model_validate(_found(lambda: check_added_link(s, collection_slug, link)))
        finally:
            s.rollback()
