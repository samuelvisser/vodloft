from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.services.check_frequency import full_scan_done, full_scan_due
from backend.db.core import run_write_transaction
from backend.db.models import Episode, Collection
from backend.services.thumbnails import newest_media_item_id, keep_own_pictures
from backend.services.sites import collection_site
from backend.types.collection_contracts import collection_contract
from sources import Feature, get_source
from task_manager.events.transactional import queue_event
from ._helpers import get_collections
from ...helpers.listed_collections import index_listed_collection, listing_steps
from ...helpers.progress import PlanStep, report_plan, update_progress
from progress_plan import PlanTracker, StageSpec


logger = logging.getLogger(__name__)
# After saving the new episodes, while their missing pictures are looked for.
_CHECKING_THUMBNAILS_PROGRESS = 95

COLLECTION_INDEXED_EVENT = "collection.indexed"


@dataclass(frozen=True)
class CollectionEpisodeScanResult:
    collection_id: int
    collection_slug: str
    collection_title: str
    episodes_found: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "collection_slug": self.collection_slug,
            "collection_title": self.collection_title,
            "episodes_found": self.episodes_found,
        }


@dataclass(frozen=True)
class FetchNewEpisodesResult:
    collections: tuple[CollectionEpisodeScanResult, ...]
    dry_run: bool = False

    @property
    def episodes_found(self) -> int:
        return sum(collection.episodes_found for collection in self.collections)

    @property
    def collections_scanned(self) -> int:
        return len(self.collections)

    def summary(self) -> str:
        if self.dry_run:
            return "Dry-run episode scan completed"
        if self.collections_scanned == 1:
            only = self.collections[0]
            return f"Episode scan finished for {only.collection_title}: {only.episodes_found} new {'episode' if only.episodes_found == 1 else 'episodes'} found"
        return f"Episode scan finished for {self.collections_scanned} collections: {self.episodes_found} new {'episode' if self.episodes_found == 1 else 'episodes'} found"

    def as_data(self) -> dict[str, Any]:
        return {
            "episodes_found": self.episodes_found,
            "collections_scanned": self.collections_scanned,
            "collections": [collection.as_dict() for collection in self.collections],
        }


async def run_fetch_new_episodes(
    s: Session,
    *,
    collection_id: Optional[int] = None,
    collection_slug: Optional[str] = None,
    dry_run: bool = False,
    initial_index: bool = False,
    quick_checked: bool | None = None,
    by_user: bool = False,
    progress=None,
) -> FetchNewEpisodesResult:
    """Scan one collection, or all collections. ``quick_checked`` limits a scan of all collections to the
    collections whose Source has quick checks (True), which get a full re-scan once a day,
    or to the other collections (False). ``by_user`` says the user's own change to the collection asked for the
    scan (see ``index_listed_collection``)."""

    collections: Sequence[Collection] = get_collections(s, collection_id=collection_id, collection_slug=collection_slug)
    if quick_checked is not None and collection_id is None and not collection_slug:
        collections = [collection for collection in collections if get_source(collection.source_key).has(Feature.QUICK_CHECK) == quick_checked]
    if collection_id is None and not collection_slug:
        # Each Collection's check frequency: on its own schedule it is left out, checked less often it skips scans.
        collections = [collection for collection in collections if full_scan_due(collection)]
    collection_ids = [collection.id for collection in collections]
    # A scan of one collection shows its steps; a scan of many how far it is with all of them.
    alone = len(collection_ids) == 1
    completed: list[CollectionEpisodeScanResult] = []
    for current_collection_id in collection_ids:
        collection = s.get(Collection, current_collection_id)
        if collection is None:
            continue
        full_scan_done(current_collection_id)
        completed.append(await _index_collection(
            s, collection=collection, dry_run=dry_run, initial_index=initial_index,
            by_user=by_user, progress=progress, planned=alone,
        ))
    return FetchNewEpisodesResult(collections=tuple(completed), dry_run=dry_run)


async def _index_collection(
    s: Session,
    *,
    collection: Collection,
    dry_run: bool,
    initial_index: bool,
    by_user: bool = False,
    progress=None,
    planned: bool = False,
) -> CollectionEpisodeScanResult:
    """Add a collection's new episodes, as its Source lists them (``index_listed_collection``). ``planned`` reports its
    progress as a plan of steps, for a scan of this collection alone.

    After that its custom indexes are brought up to date, waiting scans and imports go on, and new episodes without a
    picture get a frame of their video.
    """
    result = CollectionEpisodeScanResult(
        collection_id=collection.id, collection_slug=collection.slug, collection_title=collection.title,
        episodes_found=0,
    )
    collection_id = collection.id
    source = get_source(collection.source_key)
    if not source.has(Feature.EPISODE_LISTS):
        return result
    newest = newest_media_item_id(s)
    plan = None
    if planned and not dry_run:
        media = collection_contract(collection.type).media_names_on(collection_site(collection))
        plan = PlanTracker([
            *listing_steps(s, collection),
            StageSpec(id="pictures", code="check_pictures", label=f"Checking the pictures of the new {media.plural}", unit=media.plural),
        ], sink=report_plan(progress))
        s.rollback()
    try:
        found = index_listed_collection(
            s, collection_id=collection_id, source=source, progress=progress, dry_run=dry_run, by_user=by_user,
            plan=plan, first=initial_index,
        )
        if dry_run:
            update_progress(
                progress, 100, f"Dry run complete for '{result.collection_slug}': {found} new episodes (nothing saved)",
            )
            return result
        s.rollback()
        if plan is None:
            finish_index(collection_id=collection_id, found=found, newest=newest, progress=progress)
        else:
            with plan.running("pictures"):
                finish_index(collection_id=collection_id, found=found, newest=newest, progress=PlanStep(plan, progress, "pictures"))
    except Exception:
        s.rollback()
        raise
    return replace(result, episodes_found=found)


def finish_index(*, collection_id: int, found: int, newest: int, progress=None) -> None:
    """What follows every search for a collection's new episodes, whichever Source found them.

    ``newest`` is the newest media item before the search, so the episodes added
    after it get a frame of their video when they have no picture. Whether a
    picture is missing takes a request per episode, so the progress says how far
    that check is.
    """
    from backend.services.custom_indexes import request_collection_custom_index_reconciliation

    def work(s: Session) -> list[int]:
        collection = s.get(Collection, collection_id)
        # Read before the first write: every other write waits from there until the commit.
        added = _episodes_after(s, collection_id, newest) if found else []
        if collection is not None:
            request_collection_custom_index_reconciliation(s, collection_id)
            _queue_collection_indexed(s, collection=collection, indexed_count=found)
        return added

    added = run_write_transaction(work)
    if added:
        keep_own_pictures(added, checking=_thumbnail_progress(progress))


def _thumbnail_progress(progress):
    """Report the thumbnail check about once a second: each report is a write."""
    if not progress:
        return None
    last = 0.0

    def report(checked: int, total: int) -> None:
        nonlocal last
        now = time.monotonic()
        if checked and now - last < 1:
            return
        last = now
        if isinstance(progress, PlanStep):
            progress.set(100 * checked // max(1, total), done=checked, total=total)
            return
        progress.set(
            _CHECKING_THUMBNAILS_PROGRESS, f"Checking the thumbnails of {total} new episodes: {checked} done",
            meta={"thumbnails": {"checked": checked, "total": total}},
        )

    return report


def _episodes_after(s: Session, collection_id: int, newest: int) -> list[int]:
    """The collection's episodes added after the media item ``newest``."""
    return list(s.scalars(select(Episode.id).where(Episode.collection_id == collection_id, Episode.id > newest)))


def _queue_collection_indexed(s: Session, *, collection: Collection, indexed_count: int) -> None:
    from backend.services.notifications.emitters import new_episodes_found
    new_episodes_found(s, collection, indexed_count)
    queue_event(s, COLLECTION_INDEXED_EVENT, {
        "resource_id": collection.id,
        "id": collection.id,
        "slug": collection.slug,
        "indexed_count": indexed_count,
    })
    # A folder of existing files, or an import's files, waited for these episodes before they could be matched.
    from backend.services.existing_files import start_waiting_scans
    from backend.services.imports import start_waiting_import_steps

    start_waiting_scans(s, collection)
    start_waiting_import_steps(s, collection)
