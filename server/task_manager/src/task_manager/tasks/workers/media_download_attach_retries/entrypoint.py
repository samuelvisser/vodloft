from __future__ import annotations

from task_manager.scheduler.operation_context import current_operation_ids
from task_manager.scheduler.registry import task
from task_manager.scheduler.results import TaskResult
from task_manager.scheduler.lanes import TaskLane
from task_manager.tasks.media_download_operations import attach_redownload_batches


@task(
    key="media_download_attach_retries",
    title="Queue downloads for retry",
    description="Queues the re-downloads of a Retry all under its bulk operation, a small batch at a time.",
    allowed_resource_types=("media_download",),
    # Batches already queued are skipped when it runs again.
    default_max_retries=3,
    executor_alias=TaskLane.BULK,
    tracks_progress=True,
)
async def media_download_attach_retries(
        *,
        resource_id: int | None = None,
        media_download_ids: list[int],
        progress=None,
) -> TaskResult:
    """Queue a Retry all's re-downloads under the bulk operation running this task."""
    del resource_id
    operation_ids = current_operation_ids()
    if len(operation_ids) != 1:
        raise ValueError("Queueing retries needs exactly one owning bulk operation")

    def report(handled: int, total: int) -> None:
        if progress is not None:
            progress.set(
                int(100 * handled / total) if total else 100,
                f"Queued {handled} of {total} downloads",
            )

    handled = attach_redownload_batches(
        operation_ids[0],
        media_download_ids,
        before_batch=progress.raise_if_canceled if progress is not None else None,
        after_batch=report,
    )
    return TaskResult(
        summary=f"Queued {handled} of {len(media_download_ids)} downloads for retry",
        data={"downloads_queued": handled},
    )
