"""The scans that looked at one Collection, for its Sync log."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, literal, or_, select
from sqlalchemy.orm import Session

from backend.db.json_sql import json_array_items, json_count
from backend.db.models import Collection
from task_manager.scheduler.db import TaskDefinition, TaskRun
from task_manager.scheduler.types import ResourceType, TaskStatus

_QUICK_CHECK_TASK_KEY = "quick_check_new_videos"
_SCAN_TASK_KEYS = ("fetch_new_episodes", "rescan_quick_checked_collections", _QUICK_CHECK_TASK_KEY)
_FINISHED = (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELED)

def _lists_collection(collection_id: int, *, found_something: bool = False):
    """A scan of several collections lists each collection it looked at in its result.

    With ``found_something``, only a scan that found new episodes in the collection, or could not check it.
    """
    scanned = json_array_items(TaskRun.result, "data", "collections").alias("scanned")
    entry = scanned.c.value["collection_id"].as_integer() == collection_id
    if found_something:
        entry = and_(
            entry,
            or_(
                json_count(scanned.c.value, "episodes_found") > 0,
                json_count(scanned.c.value, "failed") > 0,
            ),
        )
    return exists(select(literal(1)).select_from(scanned).where(entry))


@dataclass(frozen=True)
class CollectionScan:
    id: int
    kind: Literal["full_scan", "quick_check"]
    status: TaskStatus
    ran_at: Optional[datetime]
    episodes_found: Optional[int]


def _collection_result(run: TaskRun, collection_id: int) -> dict[str, Any]:
    data = (run.result or {}).get("data") or {}
    for scanned in data.get("collections") or []:
        if isinstance(scanned, dict) and scanned.get("collection_id") == collection_id:
            return scanned
    return {}


def _scan(run: TaskRun, collection_id: int) -> CollectionScan:
    scanned = _collection_result(run, collection_id)
    # A quick check of several collections still succeeds when one of them could not be checked.
    status = TaskStatus.FAILED if scanned.get("failed") else run.status
    found = scanned.get("episodes_found")
    return CollectionScan(
        id=run.id,
        kind="quick_check" if run.definition.key == _QUICK_CHECK_TASK_KEY else "full_scan",
        status=status,
        ran_at=run.finished_at or run.started_at or run.created_at,
        episodes_found=found if status == TaskStatus.SUCCEEDED and isinstance(found, int) else None,
    )


def collection_scans(
    s: Session, collection_slug: str, *, offset: int, limit: int, hide_empty: bool = False,
) -> tuple[list[CollectionScan], int]:
    """Finished scans that included this Collection, newest first, and how many there are.

    ``hide_empty`` leaves out the scans that succeeded without finding a new episode in it.
    """
    collection = s.scalars(select(Collection).where(Collection.slug == collection_slug)).one_or_none()
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    included = or_(
        and_(TaskRun.resource_type == ResourceType.COLLECTION, TaskRun.resource_id == collection.id),
        _lists_collection(collection.id),
    )
    # A scan of several collections names each by its id, and SQLite gives a new collection the id of a deleted one
    # that had the highest, so a scan from before the collection was added looked at another one.
    where = [
        TaskDefinition.key.in_(_SCAN_TASK_KEYS), TaskRun.status.in_(_FINISHED), included,
        TaskRun.created_at >= collection.created_at,
    ]
    if hide_empty:
        where.append(or_(TaskRun.status != TaskStatus.SUCCEEDED, _lists_collection(collection.id, found_something=True)))
    total = s.scalar(select(func.count()).select_from(TaskRun).join(TaskRun.definition).where(*where)) or 0
    runs = s.scalars(
        select(TaskRun)
        .join(TaskRun.definition)
        .where(*where)
        .order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [_scan(run, collection.id) for run in runs], total
