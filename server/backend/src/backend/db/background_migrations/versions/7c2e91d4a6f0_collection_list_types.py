"""Look up which type of list each collection of one list is, such as an album or a playlist on SoundCloud.

On SoundCloud an album and a playlist both have a set's link, so a collection of one was named "album or playlist".
A new collection keeps the type its Site gives when its link is looked up; this looks it up once for the
collections there already are. A collection whose link can't be looked up now keeps the joined name.

Revision ID: 7c2e91d4a6f0
Revises: bdf77aef4a9d
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from backend.db.core import get_session, run_write_transaction
from backend.db.models import Collection
from backend.services.sites import collection_site
from backend.types.link_season_types import CollectionKind
from sources import SectionKind, UnknownSourceError, get_source

logger = logging.getLogger(__name__)

revision = "7c2e91d4a6f0"
down_revision = "bdf77aef4a9d"
title = "Look up whether collections of one list are albums or playlists"

_TITLE = "Looking up the type of each collection's list"


def _collections() -> list[tuple[int, str, str, str]]:
    """The collections of one list on a Site with several types of list that don't know their type yet: their ids,
    titles, Sources and links."""
    session = get_session()
    try:
        found = []
        for collection in session.scalars(select(Collection).where(
            Collection.kind == CollectionKind.LIST.value, Collection.sharing_url.is_not(None),
            Collection.list_type.is_(None),
        )):
            try:
                types = collection_site(collection).types_of(SectionKind.LIST)
            except UnknownSourceError:
                continue
            if len(types) > 1:
                found.append((collection.id, collection.title, collection.source_key, collection.sharing_url))
        return found
    finally:
        session.rollback()
        session.close()


def _list_type(source_key: str, url: str) -> str | None:
    try:
        return get_source(source_key).collection_details(url).list_type
    except Exception as exc:
        logger.info("Could not look up %s for its type of list: %s", url, exc)
        return None


def _apply(collection_id: int, url: str, list_type: str) -> None:
    def work(s) -> None:
        collection = s.get(Collection, collection_id)
        # Left alone when its link changed meanwhile.
        if collection is not None and collection.sharing_url == url and collection.list_type is None:
            collection.list_type = list_type

    run_write_transaction(work)


async def migrate(context) -> None:
    collections = _collections()
    if not collections:
        return
    total = len(collections)
    context.update_progress(0, total, _TITLE)
    for done, (collection_id, title, source_key, url) in enumerate(collections, start=1):
        context.raise_if_canceled()
        list_type = await asyncio.to_thread(_list_type, source_key, url)
        if list_type is None:
            logger.info("Leaving '%s' without its type of list, because its link could not be looked up", title)
        else:
            _apply(collection_id, url, list_type)
        context.update_progress(done, total, _TITLE)
