from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from backend.db import get_session
from backend.db.models.vodloft import AcquisitionJob, SourceReference
from backend.security.permissions import principal
from backend.services.vodloft_operations import READ_KINDS

from backend.api.models.operations import TaskOperationRead
from .service import (
    cancel_operation,
    get_operation,
    list_operations,
    mark_operation_seen,
    restart_operation,
)


router = APIRouter(prefix="/operations", tags=["Operations"])


def _can_read(request, operation):
    actor = principal(request)
    if actor.role == 'admin':
        return True
    context = operation.context or {}
    if operation.kind in READ_KINDS:
        return context.get('user_key') == actor.key and actor.can_use_connection(context.get('connection_id'))
    with get_session() as session:
        if operation.kind == 'vodloft_collection_sync':
            reference = session.get(SourceReference, context.get('source_reference_id'))
        elif operation.kind == 'vodloft_acquisition':
            job = session.get(AcquisitionJob, context.get('job_id'))
            reference = session.get(SourceReference, job.reference_id) if job else None
        else:
            return False
        return bool(reference and actor.can_use_connection(reference.connection_id))


def _require_operation(request, operation_id):
    result = get_operation(operation_id)
    if result is None or not _can_read(request, result):
        raise HTTPException(404, 'Operation not found')
    return result


def _require_control(request, operation_id):
    result = _require_operation(request, operation_id)
    actor = principal(request)
    if actor.role != 'admin' and result.kind not in READ_KINDS and not (
            result.kind == 'vodloft_collection_sync' and actor.manages_library):
        raise HTTPException(403, 'This operation requires a library manager or administrator')
    return result


@router.get("", response_model=list[TaskOperationRead])
def operations(
        request: Request,
        source: str | None = None,
        resource_type: str | None = None,
        resource_id: int | None = None,
        kind: str | None = None,
        relevant: bool = False,
        limit: int = 100,
):
    """List durable high-level task operations, optionally filtered by resource."""
    result = list_operations(
        source=source,
        resource_type=resource_type,
        resource_id=resource_id,
        kind=kind,
        relevant=relevant,
        limit=limit,
    )
    return [operation for operation in result if _can_read(request, operation)]


@router.get("/{operation_id}", response_model=TaskOperationRead)
def operation(operation_id: str, request: Request):
    return _require_operation(request, operation_id)


@router.post("/{operation_id}/seen", response_model=TaskOperationRead)
def operation_seen(operation_id: str, request: Request):
    """Acknowledge a terminal UI operation after its notification was presented."""
    _require_operation(request, operation_id)
    result = mark_operation_seen(operation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Operation not found")
    return result


@router.post("/{operation_id}/cancel", response_model=TaskOperationRead)
def operation_cancel(operation_id: str, request: Request):
    """Cancel a queued/running operation and stop recoverable work."""
    _require_control(request, operation_id)
    try:
        result = cancel_operation(operation_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Operation not found")
    return result


@router.post("/{operation_id}/restart", response_model=TaskOperationRead)
def operation_restart(operation_id: str, request: Request):
    """Restart unfinished logical targets without repeating completed work."""
    operation = _require_control(request, operation_id)
    if operation.kind in READ_KINDS:
        raise HTTPException(409, 'Repeat this action in Discover or Library')
    try:
        result = restart_operation(operation_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Operation not found")
    return result
