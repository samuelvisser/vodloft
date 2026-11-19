"""Quick checks for new videos, for collections whose Source has ``Feature.QUICK_CHECK``.

A quick check asks the Source for the collection's newest items and looks up only the
ones VODLoft does not have yet, which is much cheaper than listing the whole
collection. The Source says how often each collection can be checked; the daily full
re-scan catches anything a quick check misses.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.services import check_frequency
from backend.db.core import run_write_transaction
from backend.services.check_frequency import joins_regular_checks
from backend.db.models import Episode, Collection
from config.network import is_no_internet_error
from sources import Feature, Source, get_source
from ...helpers.listed_collections import (
    add_listed_episodes, claim_listed_items, collection_links, index_listed_collection, known_episode_slugs, link_item_slugs, splits_chapters, with_chapters,
)
from backend.services.thumbnails import newest_media_item_id
from .service import finish_index

logger = logging.getLogger(__name__)

# The cron that wakes the quick check does not fire to the second.
_SLACK = timedelta(minutes=1)
_last_checked: dict[int, datetime] = {}


@dataclass(frozen=True)
class QuickCheckedCollection:
    collection_id: int
    episodes_found: int | None
    """None when the check failed."""

    def as_dict(self) -> dict[str, int | bool | None]:
        return {
            "collection_id": self.collection_id,
            "episodes_found": self.episodes_found,
            **({"failed": True} if self.episodes_found is None else {}),
        }


@dataclass(frozen=True)
class QuickCheckResult:
    checked: int
    found: int
    failed: tuple[str, ...]
    collections: tuple[QuickCheckedCollection, ...]

    def summary(self) -> str:
        if not self.checked:
            return "No collection is due for a quick check"
        collections = "collection" if self.checked == 1 else "collections"
        videos = "video" if self.found == 1 else "videos"
        text = f"Checked {self.checked} {collections}: {self.found} new {videos}"
        return f"{text}; could not check {', '.join(self.failed)}" if self.failed else text


def _due_collections(s: Session, now: datetime) -> list[tuple[Collection, Source, int]]:
    """The collections whose quick check is due, with their Source and episode count."""
    counts = dict(s.execute(select(Episode.collection_id, func.count()).group_by(Episode.collection_id)).all())
    by_source: dict[str, list[Collection]] = {}
    for collection in s.scalars(select(Collection).order_by(Collection.id)).all():
        if get_source(collection.source_key).has(Feature.QUICK_CHECK) and joins_regular_checks(collection):
            by_source.setdefault(collection.source_key, []).append(collection)
    due = []
    for source_key, collections in by_source.items():
        source = get_source(source_key)
        minutes = source.quick_check_minutes([
            (link.url, counts.get(collection.id, 0)) for collection in collections for link in collection.links
        ])
        for collection in collections:
            last = _last_checked.get(collection.id)
            wait = timedelta(minutes=check_frequency.quick_check_minutes(collection, minutes))
            if last is None or now - last >= wait - _SLACK:
                due.append((collection, source, counts.get(collection.id, 0)))
    return due


def _check_collection(s: Session, *, collection: Collection, source: Source) -> int:
    """Look at the newest videos of each of the collection's links, and add the ones it does not have yet."""
    collection_id = collection.id
    collection_known = known_episode_slugs(s, collection)
    split = splits_chapters(collection)
    links = [(link_id, url, link_item_slugs(s, link_id)) for link_id, url in collection_links(s, collection_id)]
    # No transaction stays open while the Source looks videos up.
    s.rollback()
    added = 0
    newest = newest_media_item_id(s)
    s.rollback()
    for link_id, url, link_known in links:
        latest = [item for item in source.latest_items(url) if item.slug not in link_known]
        if not latest:
            continue
        # A video another link already gave the collection is only noted for this link.
        shared = {item.slug for item in latest if item.slug in collection_known}
        new = [item for item in latest if item.slug not in collection_known]
        found = [details for details in source.item_details(new).values() if details is not None] if new else []
        if split:
            found = [with_chapters(source, details) for details in found]

        def save(w: Session) -> int:
            claim_listed_items(w, collection_id=collection_id, link_id=link_id, slugs=shared)
            return add_listed_episodes(w, collection_id=collection_id, link_id=link_id, found=found)

        count = run_write_transaction(save)
        collection_known |= {details.slug for details in found}
        added += count
    if added:
        finish_index(collection_id=collection_id, found=added, newest=newest)
    return added


def run_quick_check(s: Session, *, now: datetime | None = None) -> QuickCheckResult:
    now = now or datetime.now(timezone.utc)
    due = _due_collections(s, now)
    found, failed, checked = 0, [], []
    for collection, source, count in due:
        _last_checked[collection.id] = now
        collection_id, title = collection.id, collection.title
        try:
            if count == 0:
                # A collection that was never indexed gets its full first index, so its numbering follows upload order.
                newest = newest_media_item_id(s)
                added = index_listed_collection(s, collection_id=collection_id, source=source)
                finish_index(collection_id=collection_id, found=added, newest=newest)
            else:
                added = _check_collection(s, collection=collection, source=source)
        except Exception as exc:
            s.rollback()
            if is_no_internet_error(exc):
                raise
            logger.warning("Could not check %s for new videos: %s", title, exc)
            failed.append(title)
            checked.append(QuickCheckedCollection(collection_id=collection_id, episodes_found=None))
            continue
        found += added
        checked.append(QuickCheckedCollection(collection_id=collection_id, episodes_found=added))
    return QuickCheckResult(checked=len(due), found=found, failed=tuple(failed), collections=tuple(checked))
