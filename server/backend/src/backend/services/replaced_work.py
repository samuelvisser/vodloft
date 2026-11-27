"""Work on a collection that saving its seasons replaces.

Saving the Seasons dialog, or the same settings in the Library's bulk edit, plans everything the new settings need from
the collection as it is. Work VODLoft still does for an earlier change does not have to finish first: numbering the
episodes again with renaming their files and writing their metadata, and listing the collection again. Saving stops
that work and starts what is still needed of it again under the new settings, together with what the new settings
need themselves. The review of the change says which work it replaces, rather than waiting for it.

Other work on the collection, such as a change of its identification or deleting its downloads, is the user's own
and is still waited for.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.core import get_session
from backend.db.models import Collection
from backend.services.errors import ServiceError
from backend.utils.helpers import name_in_text
from task_manager.scheduler.db import TaskOperation, TaskOperationRun, TaskRun
from task_manager.scheduler.operation_control import cancel_operation
from task_manager.scheduler.types import OperationStatus, TaskStatus

RENUMBER = "collection.renumber"
LISTING = ("collection.sync", "collection.index")
REPLACED_KINDS = (RENUMBER, *LISTING)
"""The kinds of work on a collection saving its seasons replaces."""

_ACTIVE = (OperationStatus.QUEUED.value, OperationStatus.RUNNING.value, OperationStatus.WAITING.value)
# How long saving waits for replaced work to reach a point where it can stop, such as the end of one file's metadata.
_STOP_SECONDS = 60.0


@dataclass(frozen=True)
class ReplacedWork:
    """What the replaced work was still going to do, which saving then starts again."""

    renumber: bool | None = None
    """Numbering again was stopped: whether it numbered the episodes again, or only renamed their files and wrote
    their metadata. None when there was none."""
    relist: bool | None = None
    """Listing the collection again was stopped: whether the user's change asked for it. None when there was none."""


def replaced_operations(s: Session, collection_id: int) -> list[str]:
    """The ids of the work on the collection that saving its seasons replaces, oldest first. Reading only."""
    return list(s.scalars(
        select(TaskOperation.id).where(
            TaskOperation.resource_type == "collection",
            TaskOperation.resource_id == collection_id,
            TaskOperation.kind.in_(REPLACED_KINDS),
            TaskOperation.status.in_(_ACTIVE),
        ).order_by(TaskOperation.created_at)
    ))


def stop_replaced_work(collection_slug: str) -> ReplacedWork:
    """Stop the work on the collection that saving its seasons replaces, and wait until numbering again stopped:
    renaming files undoes itself when it stops halfway, and writing metadata stops between two files. Listing the
    collection again stops before it saves anything. Returns what the work was still going to do. Raises a
    ``ServiceError`` when numbering again does not stop in time.

    Runs outside a write transaction: stopping work is a write of its own."""
    s = get_session()
    try:
        collection = s.scalar(select(Collection).where(Collection.slug == collection_slug))
        if collection is None:
            return ReplacedWork()
        title = collection.title
        work = [
            (operation.id, operation.kind, dict(operation.targets[0].task_kwargs or {}) if operation.targets else {})
            for operation in s.scalars(select(TaskOperation).where(TaskOperation.id.in_(replaced_operations(s, collection.id))))
        ]
    finally:
        s.rollback()
        s.close()
    if not work:
        return ReplacedWork()
    for operation_id, _kind, _kwargs in work:
        try:
            cancel_operation(operation_id, reason="Replaced by the new seasons settings", force=True)
        except ValueError:
            pass  # It finished meanwhile.
    # Listing the collection again changes nothing until it saves what it found, and it stops before that; numbering
    # again works on the files the save plans to move, so the save waits until it stopped.
    _wait_until_stopped([operation_id for operation_id, kind, _kwargs in work if kind == RENUMBER], title)
    renumbers = [kwargs for _id, kind, kwargs in work if kind == RENUMBER]
    listings = [kwargs for _id, kind, kwargs in work if kind in LISTING]
    return ReplacedWork(
        renumber=any(kwargs.get("renumber", True) for kwargs in renumbers) if renumbers else None,
        relist=any(kwargs.get("by_user", False) for kwargs in listings) if listings else None,
    )


def _wait_until_stopped(operation_ids: list[str], title: str) -> None:
    deadline = time.monotonic() + _STOP_SECONDS
    while True:
        s = get_session()
        try:
            running = s.scalar(
                select(TaskRun.id)
                .join(TaskOperationRun, TaskOperationRun.task_run_id == TaskRun.id)
                .where(TaskOperationRun.operation_id.in_(operation_ids), TaskRun.status == TaskStatus.RUNNING)
                .limit(1)
            )
        finally:
            s.rollback()
            s.close()
        if running is None:
            return
        if time.monotonic() > deadline:
            raise ServiceError(
                f"VODLoft is still stopping its earlier work on {name_in_text(title)}. Save again in a moment.",
            )
        time.sleep(0.25)
