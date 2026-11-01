from __future__ import annotations

from controller.db_utils import db_session
from task_manager.scheduler.registry import task
from task_manager.scheduler.results import TaskResult

from .service import run_delete_collection_downloads_worker


@task(
    key="delete_collection_downloads_worker",
    title="Delete collection downloads",
    description="Deletes selected episode files without downloading replacements.",
    allowed_resource_types=("collection",),
    default_max_retries=0,
    tracks_progress=True,
)
async def delete_collection_downloads_worker(
        *,
        resource_id: int | None = None,
        progress=None,
        local_media_profile_id: int | None = None,
        download_profiles_disabled: int = 0,
        selected_media_download_ids: list[int] | None = None,
) -> TaskResult:
    """Run an explicitly requested collection-wide download deletion."""
    if resource_id is None:
        raise ValueError("Delete collection downloads requires a collection resource")

    with db_session() as s:
        result = run_delete_collection_downloads_worker(
            s,
            collection_id=resource_id,
            local_media_profile_id=local_media_profile_id,
            download_profiles_disabled=download_profiles_disabled,
            selected_media_download_ids=selected_media_download_ids,
            progress=progress,
        )

    count = int(result.get("episode_files", 0))
    profile_count = int(result.get("local_media_profiles", 0))
    target_title = str(result.get("collection_title") or "collection")
    return TaskResult(
        summary=(
            f"Deleted downloads for {target_title}: "
            f"{count} episode {'file' if count == 1 else 'files'} deleted"
        ),
        data={
            **result,
            "episode_files": count,
            "local_media_profiles": profile_count,
        },
    )
