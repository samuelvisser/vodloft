"""Turn YouTube premieres that were added as livestreams back into videos.

Listing a collection through the YouTube API used to tag every premiere as a
Livestream, because the API gives premieres the same live details. yt-dlp says
which ones were premieres. Each Livestream episode of a listed collection is
looked up again, and one the Source now calls a video gets the identifier a
video would have had: its upload date, or its place in upload order. In a numbered
or seasonal collection that place can move the videos after it up a number,
so their identifiers change too, and their downloaded files are renamed.

Revision ID: c65c0a26c4e2
Revises: 5df6a8811f86
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select

from backend.db.core import get_session
from backend.db.core import run_write_transaction
from backend.db.models import Collection
from backend.db.models.media_item import Episode
from backend.types.collection_types import EpisodeIdentifier
from sources import MAIN_TAG, Feature, ItemRef, get_source


revision = "c65c0a26c4e2"
down_revision = "5df6a8811f86"
title = "Turn YouTube premieres tagged as livestreams into videos"

logger = logging.getLogger(__name__)
_TITLE = "Checking livestreams that may be premieres"
_LIVESTREAM_PREFIX = "livestream."
_NUMBERED = re.compile(r"^ep\.\d+$")
_SEASONAL = re.compile(r"^ep\.S\d+E\d+$")


def _candidates() -> list[tuple[int, str, list[ItemRef]]]:
    """Each listed collection with Livestream episodes: id, Source and the episodes to look up."""
    session = get_session()
    try:
        found = []
        for collection in session.scalars(select(Collection).order_by(Collection.id)):
            try:
                source = get_source(collection.source_key)
            except Exception:
                continue
            if not (source.has(Feature.EPISODE_LISTS) and source.has(Feature.QUICK_CHECK)):
                continue
            items = [
                ItemRef(slug, url) for slug, url in session.execute(
                    select(Episode.source_slug, Episode.sharing_url).where(
                        Episode.collection_id == collection.id,
                        Episode.episode_identifier.startswith(_LIVESTREAM_PREFIX),
                        Episode.removed_from_source.is_(False),
                    )
                ) if slug and url
            ]
            if items:
                found.append((collection.id, collection.source_key, items))
        return found
    finally:
        session.close()


def _videos(source_key: str, items: list[ItemRef]) -> frozenset[str]:
    """The episodes the Source now calls videos."""
    details = get_source(source_key).item_details(items)
    return frozenset(slug for slug, found in details.items() if found is not None and found.tag == MAIN_TAG)


def _uploaded(episode: Episode) -> tuple[datetime, int]:
    published = episode.published_date or datetime.min.replace(tzinfo=timezone.utc)
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published, episode.index


def _new_identifiers(collection: Collection, episodes: list[Episode], videos: list[Episode]) -> dict[int, str]:
    """The identifier every episode that changes gets, by episode id."""
    from task_manager.tasks.helpers.general import datetime_to_string

    scheme = EpisodeIdentifier(collection.episode_identifier)
    if scheme is EpisodeIdentifier.DATE_BASED:
        taken = {episode.episode_identifier for episode in episodes}
        identifiers = {}
        for video in sorted(videos, key=_uploaded):
            identifier = f"ep.{datetime_to_string(_uploaded(video)[0])}"
            if identifier in taken:
                # Two videos uploaded at the same moment: the second one is auxiliary.
                number = max((int(i[4:]) for i in taken if i.startswith("aux.") and i[4:].isdigit()), default=0) + 1
                identifier = f"aux.{number}"
            taken.add(identifier)
            identifiers[video.id] = identifier
        return identifiers

    pattern = _NUMBERED if scheme is EpisodeIdentifier.NUMBERED else _SEASONAL
    main = [episode for episode in episodes if pattern.match(episode.episode_identifier)] + videos
    if scheme is EpisodeIdentifier.NUMBERED:
        groups = {None: main}
    else:
        # Only the seasons a video joins are numbered again.
        affected = {video.season_id for video in videos}
        groups = {}
        for episode in main:
            if episode.season_id in affected:
                groups.setdefault(episode.season_id, []).append(episode)
    identifiers = {}
    for group in groups.values():
        for number, episode in enumerate(sorted(group, key=_uploaded), start=1):
            if scheme is EpisodeIdentifier.NUMBERED:
                identifier = f"ep.{number}"
            else:
                identifier = f"ep.S{episode.season.season_number:02d}E{number:02d}"
            if identifier != episode.episode_identifier:
                identifiers[episode.id] = identifier
    return identifiers


def _apply(collection_id: int, video_slugs: frozenset[str]) -> int:
    from task_manager.tasks.helpers.episodes.events import queue_episode_identifier_changed_event

    def work(session):
        collection = session.get(Collection, collection_id)
        if collection is None:
            return 0
        episodes = list(session.scalars(select(Episode).where(Episode.collection_id == collection_id)))
        videos = [
            episode for episode in episodes
            if episode.source_slug in video_slugs and episode.episode_identifier.startswith(_LIVESTREAM_PREFIX)
        ]
        if not videos:
            return 0
        identifiers = _new_identifiers(collection, [e for e in episodes if e not in videos], videos)
        by_id = {episode.id: episode for episode in episodes}
        old = {episode_id: by_id[episode_id].episode_identifier for episode_id in identifiers}
        # Two passes, because an identifier is unique within its collection.
        for episode_id in identifiers:
            by_id[episode_id].episode_identifier = f"premiere-fix.{episode_id}"
        session.flush()
        for episode_id, identifier in identifiers.items():
            by_id[episode_id].episode_identifier = identifier
        session.flush()
        for episode_id, identifier in old.items():
            queue_episode_identifier_changed_event(session, episode=by_id[episode_id], old_episode_identifier=identifier)
        logger.info(
            "Turned %d livestreams of collection %s into videos; %d identifiers changed",
            len(videos), collection_id, len(identifiers),
        )
        return len(videos)

    return run_write_transaction(work)


async def migrate(context) -> None:
    collections = _candidates()
    if not collections:
        return
    total = len(collections)
    context.update_progress(0, total, _TITLE)
    for done, (collection_id, source_key, items) in enumerate(collections, start=1):
        context.raise_if_canceled()
        try:
            videos = await asyncio.to_thread(_videos, source_key, items)
        except Exception as exc:
            # A collection the Source cannot look up right now keeps its tags; the others go on.
            logger.warning("Could not look up the livestreams of collection %s: %s", collection_id, exc)
            videos = frozenset()
        if videos:
            _apply(collection_id, videos)
        context.update_progress(done, total, _TITLE)
