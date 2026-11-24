from __future__ import annotations

import asyncio
import logging
from collections import Counter

from sqlalchemy import select

from backend.db.core import get_session
from backend.db.models import Collection
from backend.services.collection_health import CHECKS, check_collection_health as check_one
from config import get_settings
from task_manager.scheduler.registry import on_cron, task
from task_manager.scheduler.results import TaskResult

logger = logging.getLogger(__name__)

_TITLES = {check.kind.value: check.title for check in CHECKS}


def _collection_ids() -> list[int]:
    session = get_session()
    try:
        return list(session.scalars(select(Collection.id).order_by(Collection.id)))
    finally:
        session.rollback()
        session.close()


def _counted(counts: Counter[str]) -> str:
    return ", ".join(f"{_TITLES[kind]} in {count}" for kind, count in sorted(counts.items()))


def _check_all() -> TaskResult:
    """Run every health check on every collection."""
    collections = []
    attention: Counter[str] = Counter()
    corrected: Counter[str] = Counter()
    for collection_id in _collection_ids():
        health = check_one(collection_id)
        if health is None:
            continue
        attention.update(health.needs_attention)
        corrected.update(health.corrected)
        if health.corrected:
            logger.info("Collection %s: set right %s", health.slug, ", ".join(_TITLES[kind] for kind in health.corrected))
        collections.append({
            "slug": health.slug, "title": health.title, "healthy": health.healthy,
            "needs_attention": health.needs_attention, "corrected": health.corrected,
        })
    summary = f"Checked {len(collections)} collection(s)"
    summary += f"; needs attention: {_counted(attention)}" if attention else "; all healthy"
    if corrected:
        summary += f"; set right: {_counted(corrected)}"
    return TaskResult(summary=summary, data={
        "checked": len(collections),
        # How many collections need the user, and in how many the check set their stored health right.
        "unhealthy": sum(not item["healthy"] for item in collections),
        "set_right": sum(bool(item["corrected"]) for item in collections),
        "needs_attention": dict(attention), "corrected": dict(corrected),
        # Per collection, what the check found, so a ledger can show only the collections that need something.
        "collections": collections,
    })


@on_cron(
    # VODLoft keeps the health of a collection up to date as it works on it; this makes sure nothing drifted.
    cron=get_settings().collection_health.check_cron,
    enabled=get_settings().collection_health.check_cron_enabled,
    resource_type="system",
    resource_id=0,
    coalesce=True,
)
@task(
    key="check_collection_health",
    title="Check collection health",
    description=(
        "Makes sure every collection is healthy, and sets right what drifted, such as downloads that wait to be "
        "moved to another season, so Home and the Library show what needs you."
    ),
    allowed_resource_types=("system",),
    default_max_retries=1,
    tracks_progress=False,
)
async def check_collection_health(*, resource_id: int | None = None, progress=None) -> TaskResult:
    del resource_id, progress
    return await asyncio.to_thread(_check_all)
