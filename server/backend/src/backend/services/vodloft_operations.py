"""Durable progress records for bounded, read-only Source work."""
from contextlib import contextmanager
from datetime import datetime, timezone
import uuid

from sqlalchemy import select
from backend.db import get_session
from backend.source_manager.gateway import SourceInvocationError, cancel_running_job, clear_canceled_job
from task_manager.scheduler.db import TaskOperation
from backend.source_manager.concurrency import try_acquire, release

READ_KINDS = {'vodloft_source_resolve', 'vodloft_source_browse', 'vodloft_source_search', 'vodloft_metadata_refresh'}


@contextmanager
def tracked(kind, title, *, user_key, source_id, connection_id, item_id=None):
    acquired = try_acquire(source_id, None, connection_id)
    if acquired is None:
        raise SourceInvocationError('rate_limited', 'This Source/account is busy; try again after its current work')
    try:
        operation_id = str(uuid.uuid4())
        # Use a separate negative range from durable Collection scan IDs.
        work_key = -(int(uuid.uuid4().hex[:14], 16) + 2 ** 32)
        with get_session() as session:
            session.add(TaskOperation(id=operation_id, kind=kind, source='UI',
                resource_type='vodloft_media' if item_id is not None else 'vodloft_discovery', resource_id=item_id,
                title=title[:255], status='RUNNING', progress=None, message='Working with Source…',
                started_at=datetime.now(timezone.utc), context={'tracks_progress': False, 'user_key': user_key,
                    'source_id': source_id, 'connection_id': connection_id, 'source_job_key': work_key}))
            session.commit()
        error = None
        try:
            yield work_key
        except BaseException as exc:
            error = f'Source work stopped ({exc.code})' if isinstance(exc, SourceInvocationError) else 'Source work could not complete'
            raise
        finally:
            with get_session() as session:
                operation = session.get(TaskOperation, operation_id)
                canceled = bool(operation and operation.status == 'CANCELED')
                if operation and operation.status != 'CANCELED':
                    operation.status = 'FAILED' if error else 'SUCCEEDED'
                    operation.progress, operation.error = (None if error else 100), error
                    operation.message = error or 'Source work completed'
                    operation.finished_at = datetime.now(timezone.utc)
                    session.commit()
            clear_canceled_job(work_key)
            if canceled and error is None:
                raise SourceInvocationError('unavailable', 'Source work was canceled')
    finally:
        release(acquired)


def cancel(operation_id):
    with get_session() as session:
        operation = session.get(TaskOperation, operation_id)
        if not operation or operation.kind not in READ_KINDS:
            raise ValueError('Source operation not found')
        if operation.status not in {'RUNNING', 'QUEUED', 'WAITING'}:
            return
        work_key = (operation.context or {}).get('source_job_key')
        operation.status, operation.message = 'CANCELED', 'Source work canceled'
        operation.finished_at = datetime.now(timezone.utc)
        session.commit()
    if work_key is not None:
        cancel_running_job(work_key)


def recover_interrupted_reads():
    """Read previews are safe to repeat; never pretend they survived a restart."""
    with get_session() as session:
        for operation in session.scalars(select(TaskOperation).where(TaskOperation.kind.in_(READ_KINDS),
                TaskOperation.status.in_(['RUNNING', 'QUEUED', 'WAITING']))):
            operation.status, operation.error = 'FAILED', 'Source work was interrupted by an application restart; try again'
            operation.finished_at = datetime.now(timezone.utc)
        session.commit()
