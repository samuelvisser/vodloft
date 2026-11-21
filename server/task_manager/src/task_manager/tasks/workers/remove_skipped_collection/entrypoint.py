from __future__ import annotations

from controller.db_utils import db_session
from task_manager.scheduler.registry import task
from task_manager.scheduler.results import TaskResult

from .service import run_remove_skipped_collection


@task(
    key="remove_skipped_collection",
    title="Remove a skipped collection",
    description="Deletes the files of a collection whose feed or list the user took out of the library, then the collection.",
    allowed_resource_types=("collection",),
    default_max_retries=1,
)
async def remove_skipped_collection(*, resource_id: int | None = None, progress=None) -> TaskResult:
    if resource_id is None:
        raise ValueError("Removing a skipped collection requires a collection resource")
    with db_session() as s:
        deleted = run_remove_skipped_collection(s, collection_id=resource_id, progress=progress)
    return TaskResult(
        summary=f"Deleted {deleted} {'file' if deleted == 1 else 'files'} and the collection",
        data={"downloads": deleted},
    )
