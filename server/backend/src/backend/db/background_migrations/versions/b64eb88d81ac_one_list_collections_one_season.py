"""Make a collection made from one of its creator's lists one season, numbered in the list's order.

A collection made from a creator's playlist or album used to put its videos in a season per upload year, numbered
by date. The list is the collection's one season now, such as an album, with its videos in the list's order. Each
such collection gets that season, with every video of its year seasons; a seasonal one is numbered from now on, as a
new one is, and it lists its videos from the first.

Such a collection that the creator gave more lists kept its own list out of its seasons, with its videos in seasons
per year, and knew every list of the creator, which its Seasons dialog offered. Its own list is a season now, which
its videos move to, and it is numbered by season. It only knows the lists the creator gave it.

The list is read at its Site for its order, which is why this is not part of the database migration. A collection
with downloaded files is left as it is, because its files are in the folders of its seasons; the user can change it
on its Edit page.

Revision ID: b64eb88d81ac
Revises: a877b2377fb4
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from backend.db.core import get_session, run_write_transaction
from backend.db.models import Collection, CollectionList, CollectionListItem, MediaDownloadBase
from backend.db.models.media_item import Episode
from backend.services.episode_identification import apply_identification, plan_identification
from backend.services.creators import number_by_season
from backend.services.link_seasons import SeasonFinder, made_from_list, place_in_link_seasons
from backend.services.season_order import arrange_seasons, season_year
from backend.types.collection_types import EpisodeIdentifier, EpisodeOrder
from backend.types.season_types import SeasonType
from sources import SectionKind
from sources import get_source

logger = logging.getLogger(__name__)

revision = "b64eb88d81ac"
down_revision = "a877b2377fb4"
title = "Make collections of one list one season"

_TITLE = "Making collections of one list one season"


def _collections() -> list[tuple[int, str, str, str]]:
    """The collections made from one list that still have seasons per year and no downloaded files: their ids,
    titles, Sources and links."""
    session = get_session()
    try:
        found = []
        for collection in session.scalars(
            select(Collection).where(Collection.creator_id.is_not(None), Collection.sharing_url.is_not(None))
        ):
            if not made_from_list(collection) or not any(season_year(season) is not None for season in collection.seasons):
                continue
            with_files = session.scalar(
                select(MediaDownloadBase.id).join(Episode, Episode.id == MediaDownloadBase.media_item_id)
                .where(Episode.collection_id == collection.id).limit(1)
            )
            if with_files is not None:
                logger.info("Leaving the seasons of '%s' as they are, because it has downloaded files", collection.title)
                continue
            found.append((collection.id, collection.title, collection.source_key, collection.sharing_url))
        return found
    finally:
        session.close()


def _list_order(source_key: str, url: str) -> list[str] | None:
    """The slugs of the list's videos in its order, or None when its Site could not list it now."""
    try:
        return [item.slug for item in get_source(source_key).list_items(url)]
    except Exception as exc:
        logger.info("Could not list %s for its order: %s", url, exc)
        return None


def _apply(collection_id: int, order: list[str]) -> None:
    def work(s) -> None:
        collection = s.get(Collection, collection_id)
        if collection is None or not made_from_list(collection):
            return
        years = {season.id for season in collection.seasons if season_year(season) is not None}
        if not years:
            return
        album = SeasonFinder(s, collection).list_own_season()
        episodes = list(s.scalars(
            select(Episode).where(Episode.collection_id == collection_id).order_by(Episode.index, Episode.id)
        ))
        held = {episode.source_slug for episode in episodes if episode.season_id == album.id}
        for episode in episodes:
            if episode.season_id in years and episode.source_slug not in held:
                episode.season_id = album.id
                held.add(episode.source_slug)
        # The list's videos in its order, then any other in the order they were added. Two passes, because an index is
        # unique in a collection.
        position = {slug: number for number, slug in enumerate(order)}
        ranked = sorted(episodes, key=lambda episode: (position.get(episode.video_slug, len(position)), episode.index, episode.id))
        for episode in ranked:
            episode.index = -episode.id
        s.flush()
        for number, episode in enumerate(ranked, start=1):
            episode.index = number
        s.flush()
        for season in list(collection.seasons):
            if season.id in years and not any(episode.season_id == season.id for episode in episodes):
                s.delete(season)
        s.flush()
        s.expire(collection, ["seasons"])
        identification = EpisodeIdentifier(collection.episode_identifier)
        if identification is EpisodeIdentifier.SEASONAL:
            identification = EpisodeIdentifier.NUMBERED
        apply_identification(s, collection, plan_identification(s, collection, identification))
        collection.episode_order = EpisodeOrder.OLDEST_FIRST.value
        arrange_seasons(s, collection)

    run_write_transaction(work)


def _gatherers() -> list[int]:
    """The collections that gather some of an account's lists without being the account's own collection."""
    session = get_session()
    try:
        return [
            collection.id for collection in session.scalars(select(Collection).where(Collection.creator_account_id.is_not(None)))
            if collection.creator_account.main_collection_id != collection.id
        ]
    finally:
        session.close()


def _settle_gatherer(collection_id: int) -> None:
    def work(s) -> None:
        collection = s.get(Collection, collection_id)
        if collection is None or collection.creator_account is None:
            return
        account = collection.creator_account
        listed = set(s.scalars(select(CollectionListItem.list_id).where(
            CollectionListItem.list_id.in_([link.id for link in collection.lists])
        ).distinct()))
        # The lists it only knew of, which the creator never gave it.
        for link in list(collection.lists):
            if not link.enabled and not link.added_by_user and link.season_id is None and link.id not in listed:
                collection.lists.remove(link)
                s.delete(link)
        made_of = next((
            section for section in account.sections
            if section.kind == SectionKind.LIST and section.url == collection.sharing_url
        ), None)
        link = next((link for link in collection.lists if made_of is not None and link.ref == made_of.ref), None)
        s.flush()
        if link is None or link.as_season:
            return
        link.as_season = True
        link.season = next((
            season for season in sorted(collection.seasons, key=lambda season: season.index)
            if season.season_type == SeasonType.NORMAL.value and season_year(season) is None and not season.loose
            and not any(other.season_id == season.id for other in collection.lists)
        ), None)
        s.flush()
        number_by_season(s, collection)
        place_in_link_seasons(s, collection)

    run_write_transaction(work)


async def migrate(context) -> None:
    for collection_id in _gatherers():
        _settle_gatherer(collection_id)
    collections = _collections()
    if not collections:
        return
    total = len(collections)
    context.update_progress(0, total, _TITLE)
    for done, (collection_id, title, source_key, url) in enumerate(collections, start=1):
        context.raise_if_canceled()
        order = await asyncio.to_thread(_list_order, source_key, url)
        if order is None:
            logger.info("Leaving the seasons of '%s' as they are, because its list could not be read", title)
        else:
            _apply(collection_id, order)
        context.update_progress(done, total, _TITLE)
