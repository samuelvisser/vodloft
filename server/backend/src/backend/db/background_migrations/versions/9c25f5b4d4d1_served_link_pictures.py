"""Give links whose YouTube playlist picture YouTube does not serve one that it does.

YouTube lists a playlist's own picture in sizes it never made, such as maxresdefault, and answers those with a grey
placeholder. A link now gets the largest size YouTube serves, or the still of its playlist's first video; this looks
up again the links with a playlist's own picture. A link that can't be looked up now keeps the picture it has.

Revision ID: 9c25f5b4d4d1
Revises: 7c2e91d4a6f0
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from backend.db.core import get_session, run_write_transaction
from backend.db.models import CollectionList
from sources import get_source

logger = logging.getLogger(__name__)

revision = "9c25f5b4d4d1"
down_revision = "7c2e91d4a6f0"
title = "Give links a YouTube playlist picture that YouTube serves"

_TITLE = "Looking up the pictures of YouTube playlists"
_PLAYLIST_PICTURE = "%ytimg.com/s_p/%"


def _links() -> list[tuple[int, str, str, str]]:
    """The links with a playlist's own picture: their ids, Sources, links and pictures."""
    session = get_session()
    try:
        return [tuple(row) for row in session.execute(select(
            CollectionList.id, CollectionList.source_key, CollectionList.url, CollectionList.image_path,
        ).where(CollectionList.image_path.like(_PLAYLIST_PICTURE)))]
    finally:
        session.rollback()
        session.close()


def _picture(source_key: str, url: str) -> str | None:
    try:
        return get_source(source_key).collection_details(url).image_url
    except Exception as exc:
        logger.info("Could not look up %s for its picture: %s", url, exc)
        return None


def _apply(link_id: int, was: str, picture: str) -> None:
    def work(s) -> None:
        link = s.get(CollectionList, link_id)
        # Left alone when its picture changed meanwhile.
        if link is not None and link.image_path == was:
            link.image_path = picture

    run_write_transaction(work)


async def migrate(context) -> None:
    links = _links()
    if not links:
        return
    total = len(links)
    context.update_progress(0, total, _TITLE)
    for done, (link_id, source_key, url, was) in enumerate(links, start=1):
        context.raise_if_canceled()
        picture = await asyncio.to_thread(_picture, source_key, url)
        if picture and picture != was:
            _apply(link_id, was, picture)
        context.update_progress(done, total, _TITLE)
