from __future__ import annotations

from datetime import datetime, timezone
from hashlib import blake2b
from typing import Literal, Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from backend.api.pagination import InvalidCursorError, KeysetField, decode_cursor, encode_cursor, keyset_after
from backend.api.models.tasks import (
    TaskDefinitionRead,
    TaskLedgerEntryRead,
    TaskLedgerPageRead,
    TaskRunRead,
    TaskScheduleCreate,
    TaskScheduleRead,
    TaskTriggerRead,
)

from backend.db.core import get_session, run_write_transaction
from backend.services.media_download_collection import stored_sort_text
from task_manager.scheduler.db import TaskDefinition, TaskRun, TaskSchedule
from task_manager.scheduler.executor import trigger_now as exec_trigger_now
from task_manager.scheduler.scheduler import remove_job, schedule_job
from task_manager.scheduler.types import ResourceType, TaskStatus

TaskLedgerOrder = Literal["workflow", "started_at", "finished_at", "created_at"]

_RUNNING_STATUSES = (TaskStatus.RUNNING,)
_WAITING_STATUSES = (TaskStatus.SCHEDULED, TaskStatus.QUEUED, TaskStatus.RETRY_SCHEDULED)
_NO_SORT_TIME = datetime(1970, 1, 1, tzinfo=timezone.utc)


def list_definitions() -> list[TaskDefinitionRead]:
    s = get_session()
    try:
        return [
            TaskDefinitionRead.model_validate(item)
            for item in s.scalars(select(TaskDefinition)).all()
        ]
    finally:
        s.close()


def create_schedule(body: TaskScheduleCreate) -> TaskScheduleRead:
    return run_write_transaction(lambda s: _create_schedule(s, body))


def _create_schedule(s: Session, body: TaskScheduleCreate) -> TaskScheduleRead:
    definition = s.scalar(
        select(TaskDefinition).where(TaskDefinition.key == body.definition_key)
    )
    if definition is None:
        raise ValueError(f"Unknown task definition {body.definition_key!r}")

    schedule = TaskSchedule(
        definition=definition,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        trigger=body.trigger,
        trigger_args=body.trigger_args,
        active=True,
        max_retries=body.max_retries,
    )
    s.add(schedule)
    s.flush()
    schedule.scheduler_job_id = schedule_job(
        schedule_id=schedule.id,
        def_key=definition.key,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        trigger=body.trigger,
        trigger_args=body.trigger_args,
    )
    return TaskScheduleRead.model_validate(schedule)


def delete_schedule(schedule_id: int) -> None:
    def work(s: Session) -> None:
        schedule = s.get(TaskSchedule, schedule_id)
        if schedule is not None:
            s.delete(schedule)

    run_write_transaction(work)
    remove_job(schedule_id)


def list_schedules(
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
) -> list[TaskScheduleRead]:
    s = get_session()
    try:
        stmt = select(TaskSchedule).options(joinedload(TaskSchedule.definition))
        if resource_type is not None:
            stmt = stmt.where(TaskSchedule.resource_type == resource_type)
        if resource_id is not None:
            stmt = stmt.where(TaskSchedule.resource_id == resource_id)
        return [
            TaskScheduleRead.model_validate(item)
            for item in s.scalars(stmt).all()
        ]
    finally:
        s.close()


def list_runs(
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    status: Optional[str] = None,
    definition_key: str | None = None,
) -> list[TaskRunRead]:
    s = get_session()
    try:
        stmt = (
            select(TaskRun)
            .join(TaskDefinition, TaskDefinition.id == TaskRun.definition_id)
            .options(joinedload(TaskRun.definition))
            .order_by(TaskRun.started_at.desc())
        )
        if resource_type is not None:
            stmt = stmt.where(TaskRun.resource_type == resource_type)
        if resource_id is not None:
            stmt = stmt.where(TaskRun.resource_id == resource_id)
        if status is not None:
            stmt = stmt.where(TaskRun.status == status)
        if definition_key is not None:
            stmt = stmt.where(TaskDefinition.key == definition_key)
        return [TaskRunRead.model_validate(run) for run in s.scalars(stmt).all()]
    finally:
        s.close()


def _task_ledger_cursor_filter(
    order_column,
    *,
    value: str | None,
    run_id: int,
    descending: bool,
):
    """Rows after the cursor row, comparing timestamps as the text SQLite stores.

    ``value`` is the cursor row's own stored text. Comparing a bound datetime
    instead would put a row stored without microseconds after itself, so it
    would repeat at the top of the next page.
    """
    if value is None:
        return and_(
            order_column.is_(None),
            TaskRun.id < run_id if descending else TaskRun.id > run_id,
        )

    stored = stored_sort_text(order_column)
    value_comparison = stored < value if descending else stored > value
    id_comparison = TaskRun.id < run_id if descending else TaskRun.id > run_id
    return or_(
        value_comparison,
        and_(stored == value, id_comparison),
        order_column.is_(None),
    )


def _task_ledger_collection_revision(
    session: Session,
    *,
    filters: list,
    definition_key: str | None,
    ordering,
) -> tuple[str, int]:
    """Fingerprint only the ordered task IDs matching these filters.

    Progress and other changes to a TaskRun do not invalidate a cursor unless
    they change its membership or its position in this particular collection.
    The ordered ID stream also provides the exact total without a second count
    query, and does not hydrate task objects into memory.
    """
    statement = select(TaskRun.id).where(*filters)
    if definition_key is not None:
        statement = statement.join(
            TaskDefinition,
            TaskDefinition.id == TaskRun.definition_id,
        )
    digest = blake2b(digest_size=16)
    total = 0
    for run_id in session.scalars(
        statement.order_by(*ordering)
    ).yield_per(512):
        digest.update(f"{run_id},".encode("ascii"))
        total += 1
    return digest.hexdigest(), total


def _workflow_bucket():
    """Running tasks, then tasks waiting to run, then finished ones."""
    return case(
        (TaskRun.status.in_(_RUNNING_STATUSES), 0),
        (TaskRun.status.in_(_WAITING_STATUSES), 1),
        else_=2,
    )


def _workflow_active_at():
    """Running tasks by when they started, waiting tasks by when they were queued: oldest first."""
    return case(
        (TaskRun.status.in_(_RUNNING_STATUSES), func.coalesce(TaskRun.started_at, TaskRun.created_at)),
        (TaskRun.status.in_(_WAITING_STATUSES), TaskRun.created_at),
        else_=_NO_SORT_TIME,
    )


def _workflow_finished_at():
    """Finished tasks by when they ended: newest first."""
    return case(
        (
            TaskRun.status.not_in((*_RUNNING_STATUSES, *_WAITING_STATUSES)),
            func.coalesce(TaskRun.finished_at, TaskRun.started_at, TaskRun.created_at),
        ),
        else_=_NO_SORT_TIME,
    )


def _workflow_keyset(anchor) -> list[KeysetField]:
    """The workflow ordering as keyset fields, compared as SQLite stores the timestamps."""
    return [
        KeysetField(_workflow_bucket(), anchor[0]),
        KeysetField(stored_sort_text(_workflow_active_at()), anchor[1]),
        KeysetField(stored_sort_text(_workflow_finished_at()), anchor[2], descending=True),
        KeysetField(TaskRun.id, anchor[3], descending=True),
    ]


def query_ledger(
    s: Session,
    *,
    definition_key: str | None,
    resource_type: str | None = None,
    resource_ids: list[int] | None = None,
    include_unscoped: bool = False,
    statuses: list[str] | None = None,
    started_after: datetime | None = None,
    order_by: TaskLedgerOrder = "started_at",
    order: Literal["asc", "desc"] = "desc",
    cursor: str | None = None,
    limit: int = 50,
) -> TaskLedgerPageRead:
    """Query cursor-paginated TaskRun history using a caller-owned database session."""
    filters = []
    if definition_key is not None:
        filters.append(TaskDefinition.key == definition_key)
    if resource_type is not None:
        filters.append(TaskRun.resource_type == ResourceType(resource_type))
    if resource_ids:
        scoped_ids = TaskRun.resource_id.in_(resource_ids)
        filters.append(
            or_(scoped_ids, TaskRun.resource_id.is_(None))
            if include_unscoped else scoped_ids
        )
    elif include_unscoped:
        filters.append(TaskRun.resource_id.is_(None))
    if statuses:
        filters.append(TaskRun.status.in_([TaskStatus(status) for status in statuses]))
    if started_after is not None:
        filters.append(TaskRun.started_at >= started_after)

    cursor_scope = {
        "definition_key": definition_key,
        "resource_type": resource_type,
        "resource_ids": sorted(resource_ids or []),
        "include_unscoped": include_unscoped,
        "statuses": sorted(statuses or []),
        "started_after": started_after.isoformat() if started_after is not None else None,
    }

    workflow = order_by == "workflow"
    descending = order == "desc"
    if workflow:
        # Like the Downloads list: what runs now, then what waits, then history.
        order_column = None
        ordering = (
            _workflow_bucket().asc(),
            _workflow_active_at().asc(),
            _workflow_finished_at().desc(),
            TaskRun.id.desc(),
        )
    else:
        order_column = {
            "started_at": TaskRun.started_at,
            "finished_at": TaskRun.finished_at,
            "created_at": TaskRun.created_at,
        }[order_by]
        ordering = (
            order_column.desc().nulls_last() if descending else order_column.asc().nulls_last(),
            TaskRun.id.desc() if descending else TaskRun.id.asc(),
        )

    revision, total = _task_ledger_collection_revision(
        s,
        filters=filters,
        definition_key=definition_key,
        ordering=ordering,
    )

    if cursor:
        try:
            values = decode_cursor(cursor)
            if (
                values.get("kind") != "task-ledger"
                or values.get("order_by") != order_by
                or values.get("order") != order
                or values.get("scope") != cursor_scope
            ):
                raise InvalidCursorError("Cursor does not match this task ledger")
            cursor_id = values.get("id")
            if not isinstance(cursor_id, int) or isinstance(cursor_id, bool):
                raise InvalidCursorError("Invalid task ledger cursor id")
            if values.get("revision") == revision:
                # Resolve the cursor row's current sort key to avoid skips when its
                # timestamp moves without changing its relative rank.
                anchor_columns = (
                    (
                        _workflow_bucket(),
                        stored_sort_text(_workflow_active_at()),
                        stored_sort_text(_workflow_finished_at()),
                        TaskRun.id,
                    )
                    if workflow else (stored_sort_text(order_column),)
                )
                anchor_stmt = select(*anchor_columns).where(TaskRun.id == cursor_id, *filters)
                if definition_key is not None:
                    anchor_stmt = anchor_stmt.join(
                        TaskDefinition,
                        TaskDefinition.id == TaskRun.definition_id,
                    )
                anchor = s.execute(anchor_stmt).first()
                if anchor is None:
                    raise InvalidCursorError("Invalid task ledger cursor id")
                filters.append(
                    keyset_after(_workflow_keyset(anchor))
                    if workflow
                    else _task_ledger_cursor_filter(
                        order_column,
                        value=anchor[0],
                        run_id=cursor_id,
                        descending=descending,
                    )
                )
            # Otherwise restart at the first page. The shared lazy collection
            # reconciles mismatched page revisions using the authoritative head.
        except (InvalidCursorError, ValueError) as exc:
            raise ValueError(str(exc)) from exc

    run_stmt = (
        select(TaskRun)
        .options(joinedload(TaskRun.definition))
        .where(*filters)
    )
    if definition_key is not None:
        run_stmt = run_stmt.join(
            TaskDefinition,
            TaskDefinition.id == TaskRun.definition_id,
        )

    runs = list(s.scalars(
        run_stmt
        .order_by(*ordering)
        .limit(limit + 1)
    ).all())
    has_more = len(runs) > limit
    runs = runs[:limit]

    next_cursor = None
    if has_more and runs:
        last = runs[-1]
        next_cursor = encode_cursor({
            "kind": "task-ledger",
            "order_by": order_by,
            "order": order,
            "scope": cursor_scope,
            "revision": revision,
            "id": last.id,
        })

    items = [TaskLedgerEntryRead.model_validate(run) for run in runs]
    return TaskLedgerPageRead(
        items=items,
        total=total,
        limit=limit,
        next_cursor=next_cursor,
        revision=revision,
    )


def list_ledger(
    *,
    definition_key: str | None,
    resource_type: str | None = None,
    resource_ids: list[int] | None = None,
    include_unscoped: bool = False,
    statuses: list[str] | None = None,
    started_after: datetime | None = None,
    order_by: TaskLedgerOrder = "started_at",
    order: Literal["asc", "desc"] = "desc",
    cursor: str | None = None,
    limit: int = 50,
) -> TaskLedgerPageRead:
    s = get_session()
    try:
        return query_ledger(
            s,
            definition_key=definition_key,
            resource_type=resource_type,
            resource_ids=resource_ids,
            include_unscoped=include_unscoped,
            statuses=statuses,
            started_after=started_after,
            order_by=order_by,
            order=order,
            cursor=cursor,
            limit=limit,
        )
    finally:
        s.close()


def trigger_now(
    definition_key: str,
    resource_type: str,
    resource_id: Optional[int],
    max_retries: Optional[int] = None,
    **kwargs,
) -> TaskTriggerRead:
    return TaskTriggerRead(
        job_id=exec_trigger_now(
            def_key=definition_key,
            resource_type=resource_type,
            resource_id=resource_id,
            max_retries=max_retries,
            **kwargs,
        )
    )
