from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from backend.db.core import get_session
from backend.db.models import Collection
from backend.services.reconcile import check_moves_waiting as check_collection
from task_manager.scheduler.registry import on_cron, task
from task_manager.scheduler.results import TaskResult

logger = logging.getLogger(__name__)


def _collection_ids() -> list[int]:
    session = get_session()
    try:
        return list(session.scalars(select(Collection.id).order_by(Collection.id)))
    finally:
        session.rollback()
        session.close()


def _check_all() -> TaskResult:
    """Count each collection's downloads that wait to be moved again, and fix the counts that drifted."""
    waiting = fixed = 0
    for collection_id in _collection_ids():
        result = check_collection(collection_id)
        if result is None:
            continue
        stored, now = result
        if now:
            waiting += 1
        if stored != now:
            fixed += 1
            logger.info("Collection %s had %s downloads to move stored, but %s wait", collection_id, stored, now)
    summary = (
        f"{waiting} collection(s) have downloads to move" if waiting else "No collection has downloads to move"
    ) + (f"; corrected {fixed} count(s)" if fixed else "")
    return TaskResult(summary=summary, data={"waiting": waiting, "fixed": fixed})


@on_cron(
    # Each placement of a collection's videos keeps its count up to date; a nightly look finds what drifted.
    cron="37 3 * * *",
    resource_type="system",
    resource_id=0,
    coalesce=True,
)
@task(
    key="check_moves_waiting",
    title="Check for downloads to move",
    description=(
        "Checks every collection for downloads that its season settings put in another season, so Home and the "
        "Library show each one that waits for its Move action."
    ),
    allowed_resource_types=("system",),
    default_max_retries=1,
    tracks_progress=False,
)
async def check_moves_waiting(*, resource_id: int | None = None, progress=None) -> TaskResult:
    del resource_id, progress
    return await asyncio.to_thread(_check_all)
