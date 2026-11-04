"""Fill in the length and uploader of episodes indexed without them.

Rules in Which episodes filter on an episode's length, so every episode needs
one. Episodes of a Source that lists its episodes are asked for again when
VODLoft has no length or uploader for them: listing a collection with those
episodes left out of the known ones returns their details, through the YouTube
API when there is a key, and otherwise one lookup a video. Episodes the Source
no longer has keep what they have. The Daily Wire's episodes already have
their length, and their uploader comes from the show.

Revision ID: 4dac3ac7c70e
Revises: e7cc98e77a6a
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import or_, select

from backend.db.core import get_session
from backend.db.models import Collection
from backend.db.models.media_item import Episode
from sources import Feature, get_source


revision = "4dac3ac7c70e"
down_revision = "e7cc98e77a6a"
title = "Fill in the length and uploader of episodes"

logger = logging.getLogger(__name__)
_TITLE = "Looking up episode lengths"


def _collections() -> list[tuple[int, str, str, frozenset[str], frozenset[str]]]:
    """Each listed collection with episodes to complete: id, Source, link, known slugs and slugs to complete."""
    session = get_session()
    try:
        found = []
        for collection in session.scalars(select(Collection).order_by(Collection.id)):
            try:
                source = get_source(collection.source_key)
            except Exception:
                continue
            if not source.has(Feature.EPISODE_LISTS):
                continue
            rows = session.execute(
                select(Episode.source_slug, Episode.duration, Episode.author_name, Episode.removed_from_source)
                .where(Episode.collection_id == collection.id)
            ).all()
            missing = frozenset(
                slug for slug, duration, author, removed in rows
                if not removed and (not duration or duration <= 0 or not author)
            )
            if missing:
                known = frozenset(slug for slug, *_ in rows) - missing
                found.append((collection.id, collection.source_key, collection.sharing_url, known, missing))
        return found
    finally:
        session.close()


def _apply(collection_id: int, details: dict) -> int:
    session = get_session()
    try:
        changed = 0
        for episode in session.scalars(
            select(Episode).where(Episode.collection_id == collection_id, Episode.source_slug.in_(details))
        ):
            found = details[episode.source_slug]
            if found.duration and found.duration > 0 and not (episode.duration and episode.duration > 0):
                episode.duration = found.duration
                changed += 1
            if found.author_name and not episode.author_name:
                episode.author_name = found.author_name
        session.commit()
        return changed
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _list(source_key: str, url: str, known: frozenset[str], missing: frozenset[str]) -> dict:
    found = {}
    for details in get_source(source_key).list_episodes(url, known=known):
        if details.slug in missing:
            found[details.slug] = details
        if len(found) == len(missing):
            break
    return found


async def migrate(context) -> None:
    collections = _collections()
    if not collections:
        return
    total = len(collections)
    context.update_progress(0, total, _TITLE)
    for done, (collection_id, source_key, url, known, missing) in enumerate(collections, start=1):
        context.raise_if_canceled()
        try:
            details = await asyncio.to_thread(_list, source_key, url, known, missing)
        except Exception as exc:
            # One collection the Source cannot list right now does not stop the others.
            logger.warning("Could not look up the episodes of collection %s: %s", collection_id, exc)
            details = {}
        if details:
            _apply(collection_id, details)
        context.update_progress(done, total, _TITLE)
