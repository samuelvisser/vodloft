"""Tell each collection whether its link is a channel or one list, and make a collection of one list one season.

A collection says what its own link is: a channel, a creator's page of all their uploads or one of its feeds, or one
list, such as a playlist or an album. Every collection on a Site without creators is a list. Only a channel
collection takes the lists of its channel and can be in a creator, so a collection of a list that was in one leaves
it; nothing it holds changes.

A collection of one list used to put its videos in a season per upload year, numbered by date. The list is the
collection's one season now, with its videos in the list's order. Each such collection gets that season, with every
video of its year seasons; a seasonal one is numbered from now on, as a new one is.

The list is read at its Site for its order, which is why this is not part of the database migration. A collection
with downloaded files keeps its seasons, because its files are in their folders, and is set to a season per year; the
user can change it in its Seasons dialog.

Revision ID: ec22487a3a11
Revises: ecb0f787c77a
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from backend.db.core import get_session, run_write_transaction
from backend.db.models import Collection, MediaDownloadBase, Season
from backend.db.models.media_item import Episode
from backend.services.episode_identification import number_episodes, save_numbers
from backend.services.link_seasons import SeasonFinder, made_from_list
from backend.services.season_order import arrange_seasons, season_year
from backend.services.season_state import apply_state, load_state
from backend.services.sites import collection_kind
from backend.types.collection_types import EpisodeIdentifier, EpisodeOrder
from backend.types.link_season_types import CollectionKind, LooseVideos
from backend.types.season_types import SeasonOrigin, SeasonType
from sources import UnknownSourceError, get_source

logger = logging.getLogger(__name__)

revision = "ec22487a3a11"
down_revision = "ecb0f787c77a"
title = "Tell channel collections from collections of one list"

_TITLE = "Making collections of one list one season"


def _set_kinds() -> None:
    """Give every collection its kind, told from its link without asking its Site. A collection of one list takes
    its seasons as the list's own, unless it has a season per year."""
    session = get_session()
    try:
        rows = session.execute(select(Collection.id, Collection.sharing_url, Collection.source_key, Collection.kind)).all()
    finally:
        session.rollback()
        session.close()
    changed: dict[int, str] = {}
    for collection_id, url, source_key, stored in rows:
        try:
            kind = collection_kind(url, source_key).value
        except UnknownSourceError:
            continue
        if kind != stored:
            changed[collection_id] = kind
    if not changed:
        return

    def work(s) -> None:
        for collection in s.scalars(select(Collection).where(Collection.id.in_(changed))):
            collection.kind = changed[collection.id]
            if collection.kind != CollectionKind.LIST.value:
                continue
            # Only a channel collection is grouped under a creator.
            collection.creator_id = None
            if collection.sharing_url is not None:
                for season in collection.seasons:
                    if season.season_type == SeasonType.NORMAL.value and not season.loose and season_year(season) is None:
                        season.origin = SeasonOrigin.LIST.value
                # Its seasons per year stay until the list is made its one season below, and do when it can't be.
                if any(season_year(season) is not None for season in collection.seasons):
                    collection.loose_videos = LooseVideos.BY_YEAR.value

    run_write_transaction(work)


def _collections() -> list[tuple[int, str, str, str]]:
    """The collections made from one list that still have seasons per year and no downloaded files: their ids,
    titles, Sources and links."""
    session = get_session()
    try:
        found = []
        for collection in session.scalars(select(Collection).where(Collection.sharing_url.is_not(None))):
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
        state = load_state(s, collection)
        draft = SeasonFinder(state).list_own_season()
        apply_state(s, state)
        # Saved, the season has its own id.
        album = s.get(Season, draft.id)
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
        numbered = load_state(s, collection)
        save_numbers(s, numbered, number_episodes(numbered, identification))
        collection.episode_order = EpisodeOrder.OLDEST_FIRST.value
        collection.loose_videos = LooseVideos.ONE_SEASON.value
        arrange_seasons(s, collection)

    run_write_transaction(work)


async def migrate(context) -> None:
    _set_kinds()
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
