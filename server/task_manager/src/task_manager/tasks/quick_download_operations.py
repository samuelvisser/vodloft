"""The quick.download operation: one quick download, from queue to ready file.

Quick downloads share the transfer slots of maxConcurrentDownloads with
media downloads and claim free slots before them, because someone is waiting
for the file. They have no domain row: the operation's context and the
worker's input say what to download, and the ready folder says what came of it.
"""
from __future__ import annotations

import logging
from sqlalchemy import exists, select
from sqlalchemy.orm import Session, selectinload

from backend.db.core import get_session
from backend.services.quick_downloads import QuickDownloadRequest
from task_manager.scheduler.db import TaskDefinition, TaskOperation, TaskOperationRun, TaskOperationTarget, TaskRun
from task_manager.scheduler.operation_context import current_operation_ids
from task_manager.scheduler.operations import (
    OperationTargetSpec,
    create_operation,
    link_run_to_operations,
    operation_target_needs_dispatch,
)
from task_manager.scheduler.transactional import queue_task_after_commit
from task_manager.scheduler.types import OperationSource, OperationStatus, ResourceType, TaskStatus

logger = logging.getLogger(__name__)

QUICK_DOWNLOAD_OPERATION_KIND = "quick.download"
QUICK_DOWNLOAD_TASK_KEY = "quick_download"
_STARTED_CONTEXT_KEY = "quick_download_started"
INTERRUPTED_MESSAGE = "Interrupted by a VODLoft restart"
_ACTIVE_OPERATION_STATUSES = (
    OperationStatus.QUEUED.value,
    OperationStatus.RUNNING.value,
    OperationStatus.WAITING.value,
)


def create_quick_download_operation(session: Session, request: QuickDownloadRequest) -> TaskOperation:
    """Queue one quick download. The caller dispatches the download queue afterwards."""
    target = OperationTargetSpec(
        task_key=QUICK_DOWNLOAD_TASK_KEY,
        resource_type=ResourceType.QUICK_DOWNLOAD.value,
        resource_id=None,
        task_kwargs={"request": request.task_input()},
        slot_key=f"quick-download:{request.id}",
        # Shares the constrained download queue; its dispatcher fills slots.
        recover_on_restart=False,
    )
    return create_operation(
        session,
        kind=QUICK_DOWNLOAD_OPERATION_KIND,
        source=OperationSource.UI.value,
        resource_type=ResourceType.QUICK_DOWNLOAD.value,
        resource_id=None,
        title=request.title,
        targets=[target],
        context={
            "quick_download_id": request.id,
            "source_key": request.source_key,
            "url": request.url,
            "choice": request.choice.label,
            "kind": request.choice.kind,
        },
    )


def active_quick_download_operations(session: Session) -> list[TaskOperation]:
    return list(session.scalars(
        select(TaskOperation)
        .where(
            TaskOperation.kind == QUICK_DOWNLOAD_OPERATION_KIND,
            TaskOperation.status.in_(_ACTIVE_OPERATION_STATUSES),
        )
        .order_by(TaskOperation.created_at.asc(), TaskOperation.id.asc())
    ))


def quick_download_operation(session: Session, quick_id: str) -> TaskOperation | None:
    """The newest operation of one quick download, active or not."""
    return session.scalar(
        select(TaskOperation)
        .where(
            TaskOperation.kind == QUICK_DOWNLOAD_OPERATION_KIND,
            TaskOperation.context["quick_download_id"].as_string() == quick_id,
        )
        .order_by(TaskOperation.created_at.desc())
        .limit(1)
    )


def _reserve(session: Session, operation: TaskOperation, definition_id: int) -> bool:
    """Reserve a SCHEDULED TaskRun for the operation, as media downloads do, so the slot counts at once."""
    target = operation.targets[0]
    if not operation_target_needs_dispatch(session, operation.id, target.slot_key):
        return False
    task_kwargs = dict(target.task_kwargs or {})
    run = TaskRun(
        schedule_id=None,
        definition_id=definition_id,
        resource_type=ResourceType.QUICK_DOWNLOAD,
        resource_id=None,
        status=TaskStatus.SCHEDULED,
        progress=0,
        result=None,
        attempt_count=0,
        max_retries=1,
        meta={"inputs": task_kwargs},
    )
    session.add(run)
    session.flush()
    link_run_to_operations(
        session, run=run, task_key=target.task_key,
        operation_ids=(operation.id,), operation_slot=target.slot_key,
    )
    queue_task_after_commit(
        session,
        def_key=target.task_key,
        resource_type=target.resource_type,
        resource_id=None,
        operation_ids=(operation.id,),
        operation_slot=target.slot_key,
        run_id=run.id,
        **task_kwargs,
    )
    return True


def dispatch_queued_quick_downloads(session: Session, *, budget: int) -> int:
    """Start queued quick downloads, oldest first, in up to ``budget`` free download slots.

    Only the media download dispatcher calls this, while it holds the lock
    that serializes the shared budget.
    """
    if budget <= 0:
        return 0
    definition_id = session.scalar(select(TaskDefinition.id).where(TaskDefinition.key == QUICK_DOWNLOAD_TASK_KEY))
    if definition_id is None:
        return 0
    has_run = exists(select(TaskOperationRun.task_run_id).where(
        TaskOperationRun.operation_id == TaskOperation.id,
    ))
    operations = session.scalars(
        select(TaskOperation)
        .options(selectinload(TaskOperation.targets))
        .where(
            TaskOperation.kind == QUICK_DOWNLOAD_OPERATION_KIND,
            TaskOperation.status == OperationStatus.QUEUED.value,
            ~has_run,
        )
        .order_by(TaskOperation.created_at.asc(), TaskOperation.id.asc())
        .limit(budget)
    )
    dispatched = 0
    for operation in operations:
        if operation.targets and _reserve(session, operation, definition_id):
            dispatched += 1
    return dispatched


def mark_quick_download_started() -> None:
    """Remember on the operation that its file was being made, so a restart can tell."""
    operation_ids = current_operation_ids()
    if not operation_ids:
        return
    session = get_session()
    try:
        for operation in session.scalars(select(TaskOperation).where(TaskOperation.id.in_(operation_ids))):
            operation.context = {**(operation.context or {}), _STARTED_CONTEXT_KEY: True}
        session.commit()
    finally:
        session.close()


def recover_quick_downloads() -> None:
    """After a restart: end quick downloads that were interrupted, then fill free slots.

    A file that was being made cannot be resumed (startup recovery has removed
    its folder), so its operation ends and says why. Quick downloads that never
    started stay queued and start as slots free up.
    """
    from task_manager.scheduler.operation_control import cancel_operation
    from task_manager.tasks.media_download_operations import on_media_download_task_terminal

    session = get_session()
    try:
        interrupted = [
            operation.id for operation in active_quick_download_operations(session)
            if (operation.context or {}).get(_STARTED_CONTEXT_KEY)
        ]
    finally:
        session.close()
    for operation_id in interrupted:
        try:
            cancel_operation(operation_id, reason=INTERRUPTED_MESSAGE, acknowledge=False)
        except Exception:
            logger.exception("Could not end interrupted quick download %s after a restart", operation_id)
    on_media_download_task_terminal()
