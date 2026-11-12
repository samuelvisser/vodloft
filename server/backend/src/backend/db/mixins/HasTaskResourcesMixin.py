from __future__ import annotations

import logging
from typing import ClassVar

from sqlalchemy import and_, delete, event, select
from sqlalchemy.orm import Session, declared_attr, foreign, relationship

from task_manager.after_commit import keep_until_commit

from task_manager.scheduler.types import ResourceType, TaskStatus


logger = logging.getLogger(__name__)
_PENDING_DELETED_RESOURCES_KEY = "vodloft.deleted_task_resources"
_PENDING_RELEASED_TASK_CALLBACKS_KEY = "vodloft.released_task_callbacks"


class HasTaskResourcesMixin:
    """Attach scheduler work to a domain resource through its generic resource key.

    The scheduler deliberately stores ``resource_type`` + ``resource_id`` instead
    of hard-coding one foreign key per domain model. Deleting a resource also
    deletes its schedules, runs, operations and operation targets, and callers
    can navigate those collections directly from the resource model.

    The relationships only read. ``_delete_task_rows_of_deleted_resources`` deletes
    the rows of every resource a flush deletes with one statement per table, where
    a cascade would load each resource's rows and delete them one at a time.
    """

    __task_resource_types__: ClassVar[tuple[str, ...]]

    @classmethod
    def _task_resource_values(cls) -> tuple[str, ...]:
        values = tuple(getattr(cls, "__task_resource_types__", ()))
        if not values:
            raise ValueError(
                f"{cls.__name__} uses HasTaskResourcesMixin without __task_resource_types__"
            )
        return values

    @classmethod
    def _task_resource_enums(cls) -> tuple[ResourceType, ...]:
        return tuple(ResourceType(value) for value in cls._task_resource_values())

    @declared_attr
    def task_schedules(cls):
        from task_manager.scheduler.db import TaskSchedule

        resource_types = cls._task_resource_enums()
        return relationship(
            TaskSchedule,
            primaryjoin=lambda: and_(
                foreign(TaskSchedule.resource_id) == cls.id,
                TaskSchedule.resource_type.in_(resource_types),
            ),
            viewonly=True,
            lazy="select",
            uselist=True,
        )

    @declared_attr
    def task_runs(cls):
        from task_manager.scheduler.db import TaskRun

        resource_types = cls._task_resource_enums()
        return relationship(
            TaskRun,
            primaryjoin=lambda: and_(
                foreign(TaskRun.resource_id) == cls.id,
                TaskRun.resource_type.in_(resource_types),
            ),
            viewonly=True,
            lazy="select",
            uselist=True,
        )

    @declared_attr
    def task_operations(cls):
        from task_manager.scheduler.db import TaskOperation

        resource_types = cls._task_resource_values()
        return relationship(
            TaskOperation,
            primaryjoin=lambda: and_(
                foreign(TaskOperation.resource_id) == cls.id,
                TaskOperation.resource_type.in_(resource_types),
            ),
            viewonly=True,
            lazy="select",
            uselist=True,
        )

    @declared_attr
    def task_operation_targets(cls):
        from task_manager.scheduler.db import TaskOperationTarget

        resource_types = cls._task_resource_values()
        return relationship(
            TaskOperationTarget,
            primaryjoin=lambda: and_(
                foreign(TaskOperationTarget.resource_id) == cls.id,
                TaskOperationTarget.resource_type.in_(resource_types),
            ),
            viewonly=True,
            lazy="select",
            uselist=True,
        )


def _task_status(value) -> TaskStatus:
    return value if isinstance(value, TaskStatus) else TaskStatus(value)


def _run_released_task_callbacks(callbacks: set) -> None:
    """Refill constrained task queues when deletion removes a pending reservation."""
    for callback in callbacks:
        try:
            callback()
        except Exception:
            # The domain-resource deletion has already committed. A queue refill
            # failure must never make that successful deletion appear to fail.
            logger.exception("Failed to refill task queue after resource deletion")


_PENDING_TASK_STATUSES = (TaskStatus.SCHEDULED, TaskStatus.QUEUED, TaskStatus.RETRY_SCHEDULED)
# Stays far below the number of values one SQLite statement takes.
_DELETED_RESOURCES_PER_STATEMENT = 500


def _remember_released_task_callbacks(session: Session, definition_ids: set[int]) -> None:
    """Keep the terminal callbacks of task definitions that lost a pending run, to call after the commit.

    A pending/retry TaskRun occupied a durable queue slot but has no Python
    worker still executing. Once it is deleted, a task definition's generic
    terminal callback may immediately refill that slot. RUNNING work is
    excluded: its executor invokes the callback only after cooperative
    cancellation actually leaves the worker body.
    """
    from task_manager.scheduler.db import TaskDefinition
    from task_manager.scheduler.registry import get_task

    if not definition_ids:
        return
    keys = session.scalars(select(TaskDefinition.key).where(TaskDefinition.id.in_(definition_ids))).all()
    for key in keys:
        try:
            task_meta, _ = get_task(key)
        except KeyError:
            continue
        if task_meta.terminal_callback is not None:
            session.info.setdefault(_PENDING_RELEASED_TASK_CALLBACKS_KEY, set()).add(task_meta.terminal_callback)


@event.listens_for(Session, "before_flush")
def _delete_task_rows_of_deleted_resources(session: Session, _flush_context, _instances) -> None:
    """Delete the scheduler rows of every resource this flush deletes, one statement per table.

    Operation targets, run links and dependencies of a deleted operation or run
    follow through their own foreign keys.
    """
    from task_manager.scheduler.db import TaskOperation, TaskOperationTarget, TaskRun, TaskSchedule

    ids_by_type: dict[str, set[int]] = {}
    for item in session.deleted:
        if isinstance(item, HasTaskResourcesMixin) and getattr(item, "id", None) is not None:
            for resource_type in item._task_resource_values():
                ids_by_type.setdefault(resource_type, set()).add(int(item.id))

    released_definition_ids: set[int] = set()
    for resource_type, ids in ids_by_type.items():
        ordered = sorted(ids)
        for start in range(0, len(ordered), _DELETED_RESOURCES_PER_STATEMENT):
            chunk = ordered[start:start + _DELETED_RESOURCES_PER_STATEMENT]
            runs = and_(TaskRun.resource_type == ResourceType(resource_type), TaskRun.resource_id.in_(chunk))
            released_definition_ids.update(session.scalars(
                select(TaskRun.definition_id).where(runs, TaskRun.status.in_(_PENDING_TASK_STATUSES)).distinct()
            ))
            for statement in (
                delete(TaskOperationTarget).where(
                    TaskOperationTarget.resource_type == resource_type, TaskOperationTarget.resource_id.in_(chunk)),
                delete(TaskOperation).where(
                    TaskOperation.resource_type == resource_type, TaskOperation.resource_id.in_(chunk)),
                delete(TaskRun).where(runs),
                delete(TaskSchedule).where(
                    TaskSchedule.resource_type == ResourceType(resource_type), TaskSchedule.resource_id.in_(chunk)),
            ):
                session.execute(statement, execution_options={"synchronize_session": False})
    _remember_released_task_callbacks(session, released_definition_ids)


@event.listens_for(Session, "after_flush")
def _remember_deleted_task_resources(session: Session, flush_context) -> None:
    from task_manager.scheduler.db import TaskRun

    resources: set[tuple[str, int]] = session.info.setdefault(
        _PENDING_DELETED_RESOURCES_KEY,
        set(),
    )
    released_definition_ids: set[int] = set()

    for item in session.deleted:
        if isinstance(item, TaskRun):
            if _task_status(item.status) in _PENDING_TASK_STATUSES:
                released_definition_ids.add(item.definition_id)

        if not isinstance(item, HasTaskResourcesMixin):
            continue
        resource_id = getattr(item, "id", None)
        if resource_id is None:
            continue
        for resource_type in item._task_resource_values():
            resources.add((resource_type, int(resource_id)))

    _remember_released_task_callbacks(session, released_definition_ids)

    if not resources:
        session.info.pop(_PENDING_DELETED_RESOURCES_KEY, None)


@event.listens_for(Session, "after_commit")
def _remove_deleted_resource_jobs(session: Session) -> None:
    # A nested SAVEPOINT committed, but the outer transaction is still pending.
    if session.in_nested_transaction():
        return

    resources = session.info.pop(_PENDING_DELETED_RESOURCES_KEY, set())
    callbacks = session.info.pop(_PENDING_RELEASED_TASK_CALLBACKS_KEY, set())

    if resources:
        from task_manager.scheduler.scheduler import cancel_pending_resource_jobs

        cancel_pending_resource_jobs(resources)

    _run_released_task_callbacks(callbacks)


@event.listens_for(Session, "after_rollback")
def _discard_deleted_resource_jobs(session: Session) -> None:
    session.info.pop(_PENDING_DELETED_RESOURCES_KEY, None)
    session.info.pop(_PENDING_RELEASED_TASK_CALLBACKS_KEY, None)


# A SAVEPOINT that rolls back only drops what was queued inside it.
keep_until_commit(_PENDING_DELETED_RESOURCES_KEY, _PENDING_RELEASED_TASK_CALLBACKS_KEY)
