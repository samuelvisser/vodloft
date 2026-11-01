from __future__ import annotations

from backend.security.access import Access, Area

from backend.api.models.operations import TaskOperationRead
from task_manager.scheduler.operation_control import (
    cancel_operation as cancel_task_operation,
    restart_operation as restart_task_operation,
)
from task_manager.tasks.media_download_operations import (
    MEDIA_DOWNLOAD_OPERATION_KIND,
    cancel_media_download_operation,
    restart_media_download_operation,
)
from task_manager.scheduler.operations import (
    get_operation as get_task_operation,
    list_operations as list_task_operations,
    mark_operation_seen as mark_task_operation_seen,
)


def _read(snapshot) -> TaskOperationRead | None:
    return TaskOperationRead.model_validate(snapshot) if snapshot is not None else None


def _visible_to(access: Access, snapshot) -> bool:
    return access.allows(Area.TASKS) or (
        access.user_id is not None and snapshot.requested_by_user_id == access.user_id
    )


def list_operations(
        access: Access,
        *,
        source: str | None = None,
        resource_type: str | None = None,
        resource_id: int | None = None,
        kind: str | None = None,
        relevant: bool = False,
        limit: int = 100,
) -> list[TaskOperationRead]:
    return [
        TaskOperationRead.model_validate(snapshot)
        for snapshot in list_task_operations(
            source=source,
            resource_type=resource_type,
            resource_id=resource_id,
            kind=kind,
            relevant=relevant,
            limit=limit,
            requested_by_user_id=None if access.allows(Area.TASKS) else access.user_id or -1,
        )
    ]


def get_operation(access: Access, operation_id: str) -> TaskOperationRead | None:
    snapshot = get_task_operation(operation_id)
    if snapshot is None or not _visible_to(access, snapshot):
        return None
    return _read(snapshot)


def mark_operation_seen(access: Access, operation_id: str) -> TaskOperationRead | None:
    if get_operation(access, operation_id) is None:
        return None
    return _read(mark_task_operation_seen(operation_id))


def cancel_operation(operation_id: str) -> TaskOperationRead | None:
    operation = get_task_operation(operation_id)
    if operation is not None and operation.kind == MEDIA_DOWNLOAD_OPERATION_KIND:
        return _read(cancel_media_download_operation(operation_id))
    return _read(cancel_task_operation(operation_id))


def restart_operation(operation_id: str) -> TaskOperationRead | None:
    operation = get_task_operation(operation_id)
    if operation is not None and operation.kind == MEDIA_DOWNLOAD_OPERATION_KIND:
        return _read(restart_media_download_operation(operation_id))
    return _read(restart_task_operation(operation_id))
