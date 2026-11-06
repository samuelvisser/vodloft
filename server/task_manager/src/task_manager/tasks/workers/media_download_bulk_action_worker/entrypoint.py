from __future__ import annotations

from backend.services.download_actions import (
    cancel_media_download_action,
    delete_media_download_artifact_action,
    delete_unavailable_media_download_action,
)
from task_manager.scheduler.operation_context import current_operation_ids
from task_manager.scheduler.registry import task
from task_manager.scheduler.results import TaskResult
from task_manager.tasks.media_download_operations import attach_redownload_batches


@task(
    key="media_download_bulk_action_worker",
    title="Bulk download action",
    description=(
        "Coordinates bulk retry, cancel, artifact deletion, and unavailable-record deletion actions."
    ),
    allowed_resource_types=("media_download",),
    # Every action is safe to repeat, so a target that hit a locked database
    # tries again instead of silently dropping its download from the bulk action.
    default_max_retries=3,
    executor_alias="bulk",
    tracks_progress=True,
)
async def media_download_bulk_action_worker(
        *,
        resource_id: int | None = None,
        media_download_id: int | None = None,
        media_download_ids: list[int] | None = None,
        action: str,
        progress=None,
) -> TaskResult:
    """Execute one target of a bulk media-download action."""
    del resource_id  # Bulk targets coordinate work but do not own the MediaDownload row.
    if progress is not None:
        progress.raise_if_canceled()

    if action == "attach_retries":
        return _attach_retries(media_download_ids or [], progress)

    if media_download_id is None:
        raise ValueError(f"Bulk media download action '{action}' requires media_download_id")

    if action == "cancel":
        cancel_media_download_action(
            media_download_id,
            allow_inactive=True,
            missing_ok=True,
        )
        return TaskResult(
            summary=f"Canceled download {media_download_id}",
            data={"action": action, "media_download_id": media_download_id},
        )

    if action == "delete_artifact":
        deleted = delete_media_download_artifact_action(
            media_download_id,
            missing_ok=True,
        )
        return TaskResult(
            summary=(
                f"Deleted artifact for download {media_download_id}"
                if deleted
                else f"Download {media_download_id} no longer exists"
            ),
            data={
                "action": action,
                "media_download_id": media_download_id,
                "files_deleted": 1 if deleted else 0,
            },
        )

    if action == "delete_unavailable":
        deleted = delete_unavailable_media_download_action(
            media_download_id,
            missing_ok=True,
        )
        return TaskResult(
            summary=(
                f"Deleted download record {media_download_id}"
                if deleted
                else f"Download {media_download_id} no longer exists"
            ),
            data={
                "action": action,
                "media_download_id": media_download_id,
                "downloads_deleted": 1 if deleted else 0,
            },
        )

    raise ValueError(f"Unsupported bulk media download action: {action}")


def _attach_retries(media_download_ids: list[int], progress) -> TaskResult:
    """Queue a Retry all's re-downloads under the bulk operation running this task."""
    operation_ids = current_operation_ids()
    if len(operation_ids) != 1:
        raise ValueError("Attaching retries needs exactly one owning bulk operation")

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
        data={"action": "attach_retries", "downloads_queued": handled},
    )
