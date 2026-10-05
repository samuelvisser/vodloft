"""Account-scoped operation inspection and Collection execution controls."""
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from backend.api.models.operations import TaskOperationRead
from backend.db import get_session
from backend.db.models.vodloft import SourceReference
from backend.security.permissions import principal, require_connection
from backend.services import vodloft_sync
from task_manager.scheduler.db import TaskOperation

router = APIRouter(prefix='/vodloft', tags=['VodLoft operations'])


def _authorized(session, collection_id, operation_id, request):
    operation = session.get(TaskOperation, operation_id)
    if not operation or operation.kind != 'vodloft_collection_sync' or operation.resource_id != collection_id:
        raise HTTPException(404, 'Collection operation not found')
    reference = session.get(SourceReference, (operation.context or {}).get('source_reference_id'))
    if not reference or reference.item_id != collection_id:
        raise HTTPException(404, 'Source reference no longer exists')
    require_connection(request, reference.connection_id)
    return operation


@router.get('/library/{collection_id}/operations', response_model=list[TaskOperationRead])
def collection_operations(collection_id: int, request: Request):
    with get_session() as session:
        result = []
        for operation in session.scalars(select(TaskOperation).where(
                TaskOperation.kind == 'vodloft_collection_sync', TaskOperation.resource_id == collection_id)
                .order_by(TaskOperation.created_at.desc()).limit(50)):
            reference = session.get(SourceReference, (operation.context or {}).get('source_reference_id'))
            if reference and principal(request).can_use_connection(reference.connection_id):
                result.append(TaskOperationRead.model_validate(operation))
        return result


@router.post('/library/{collection_id}/operations/{operation_id}/cancel', status_code=204)
def cancel(collection_id: int, operation_id: str, request: Request):
    if not principal(request).manages_library:
        raise HTTPException(403, 'A library manager must cancel Collection operations')
    with get_session() as session:
        _authorized(session, collection_id, operation_id, request)
    vodloft_sync.cancel_operation(operation_id)


@router.post('/library/{collection_id}/operations/{operation_id}/resume', status_code=202)
def resume(collection_id: int, operation_id: str, request: Request):
    if not principal(request).manages_library:
        raise HTTPException(403, 'A library manager must resume Collection operations')
    with get_session() as session:
        _authorized(session, collection_id, operation_id, request)
    try:
        return {'operation_id': vodloft_sync.restart_operation(operation_id)}
    except vodloft_sync.CollectionSyncError as exc:
        raise HTTPException(409, str(exc)) from exc
