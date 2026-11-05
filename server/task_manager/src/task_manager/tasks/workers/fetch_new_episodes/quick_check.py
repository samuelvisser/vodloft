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
from backend.services.check_frequency import joins_regular_checks
from backend.db.models import Episode, Collection
from config.network import is_no_internet_error
from sources import Feature, Source, get_source
from ...helpers.listed_collections import add_listed_episodes, known_episode_slugs
from backend.services.thumbnails import newest_media_item_id, take_first_frames
from .service import _episodes_after, _index_listed_collection, _queue_collection_indexed

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
        minutes = source.quick_check_minutes([(collection.sharing_url, counts.get(collection.id, 0)) for collection in collections])
        for collection in collections:
            last = _last_checked.get(collection.id)
            wait = timedelta(minutes=check_frequency.quick_check_minutes(collection, minutes))
            if last is None or now - last >= wait - _SLACK:
                due.append((collection, source, counts.get(collection.id, 0)))
    return due


def _check_collection(s: Session, *, collection: Collection, source: Source) -> int:
    collection_id, url = collection.id, collection.sharing_url
    known = known_episode_slugs(s, collection)
    # No transaction stays open while the Source looks videos up.
    s.rollback()
    new = [item for item in source.latest_items(url) if item.slug not in known]
    if not new:
        return 0
    found = [details for details in source.item_details(new).values() if details is not None]
    newest = newest_media_item_id(s)
    added = add_listed_episodes(s, collection_id=collection_id, found=found)
    if added:
        from backend.services.custom_indexes import request_collection_custom_index_reconciliation

        request_collection_custom_index_reconciliation(s, collection_id)
        _queue_collection_indexed(s, collection=s.get(Collection, collection_id), indexed_count=added)
    s.commit()
    if added:
        take_first_frames(s, _episodes_after(s, collection_id, newest))
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
                added = _index_listed_collection(s, collection=collection, source=source, dry_run=False).episodes_found
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
