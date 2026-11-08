from __future__ import annotations

from config import get_settings

from backend.security.access import Access

from backend.api.endpoints.operations.service import list_operations
from backend.api.models.puller import FrontendPullAPIRead, FrontendPullData
from task_manager.scheduler.types import OperationStatus


_ACTIVE_OPERATION_STATUSES = {
    OperationStatus.QUEUED.value,
    OperationStatus.RUNNING.value,
    OperationStatus.WAITING.value,
}


# Every open page asks for this about once a second while work runs. Running work and what a person
# started come first; with thousands of queued downloads, a longer list only repeats queued ones,
# whose place in the queue the Downloads page reads from the server anyway.
PULL_OPERATION_LIMIT = 200


def get_frontend_pull(access: Access) -> FrontendPullAPIRead:
    """Return the frontend's generic changing-execution snapshot."""
    operations = list_operations(access, relevant=True, limit=PULL_OPERATION_LIMIT)
    has_active_operation = any(
        operation.status in _ACTIVE_OPERATION_STATUSES
        for operation in operations
    )
    return FrontendPullAPIRead(
        app_version=get_settings().app_version,
        mode="fast" if has_active_operation else "slow",
        data=FrontendPullData(operations=operations),
    )
