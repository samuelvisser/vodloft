from __future__ import annotations

import asyncio
import logging
from collections import Counter

from sqlalchemy import select

from backend.db.core import get_session
from backend.db.models import Collection
from backend.services.collection_health import (
    TITLES, check_collection_health as check_one, checks_off, creator_suggestions, find_site_creator,
)
from backend.types.collection_health_types import HealthIssueKind
from config import get_settings
from task_manager.scheduler.registry import on_cron, task
from task_manager.scheduler.results import TaskResult

logger = logging.getLogger(__name__)

_TITLES = TITLES


def _collection_ids() -> tuple[list[int], bool]:
    """Every collection, and whether the creators check is on."""
    session = get_session()
    try:
        ids = list(session.scalars(select(Collection.id).order_by(Collection.id)))
        return ids, HealthIssueKind.CREATORS.value not in checks_off(session)
    finally:
        session.rollback()
        session.close()


def _suggestions() -> int:
    session = get_session()
    try:
        return len(creator_suggestions(session))
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
    ids, creators_on = _collection_ids()
    creators_found = 0
    for collection_id in ids:
        # Finding the creator behind a collection may ask its Site, so it happens before its health is stored.
        if creators_on and find_site_creator(collection_id):
            creators_found += 1
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
    suggestions = _suggestions() if creators_on else 0
    if suggestions:
        summary += f"; {suggestions} creator(s) to group"
    return TaskResult(summary=summary, data={
        "checked": len(collections),
        # How many collections need the user, and in how many the check set their stored health right.
        "unhealthy": sum(not item["healthy"] for item in collections),
        "set_right": sum(bool(item["corrected"]) for item in collections),
        # Collections whose creator it looked up, and creators whose collections Home suggests grouping.
        "creators_found": creators_found, "suggestions": suggestions,
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
        "moved to another season, so Home and the Library show what needs you. Also finds the creator behind "
        "collections in no creator, to suggest grouping a creator's collections."
    ),
    allowed_resource_types=("system",),
    default_max_retries=1,
    tracks_progress=False,
)
async def check_collection_health(*, resource_id: int | None = None, progress=None) -> TaskResult:
    del resource_id, progress
    return await asyncio.to_thread(_check_all)
