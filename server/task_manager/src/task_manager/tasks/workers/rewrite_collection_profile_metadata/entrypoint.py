from __future__ import annotations

from backend.utils.custom_index import CustomIndexNotReadyError
from task_manager.scheduler.registry import task
from task_manager.scheduler.results import TaskResult
from task_manager.tasks.helpers.custom_index_readiness import (
    custom_index_pair_lock, pair_is_ready, request_missing_index_repair, wait_for_custom_index_pair,
)

from .service import run_rewrite_collection_profile_metadata


@task(
    key="rewrite_collection_profile_metadata",
    title="Write metadata into files",
    description="Rewrite the tags and NFO files of one collection's files for one Local Media Profile, "
                "without downloading them again.",
    allowed_resource_types=("collection",),
    default_max_retries=1,
    tracks_progress=True,
)
async def rewrite_collection_profile_metadata(
    *,
    resource_id: int | None = None,
    progress=None,
    local_media_profile_id: int | None = None,
) -> TaskResult:
    if resource_id is None or local_media_profile_id is None:
        raise ValueError("Rewriting metadata requires a Collection and Local Media Profile")
    try:
        while True:
            await wait_for_custom_index_pair(resource_id, local_media_profile_id)
            async with custom_index_pair_lock(resource_id, local_media_profile_id):
                if not pair_is_ready(resource_id, local_media_profile_id):
                    continue
                return run_rewrite_collection_profile_metadata(
                    collection_id=resource_id, local_media_profile_id=local_media_profile_id, progress=progress,
                )
    except CustomIndexNotReadyError as exc:
        request_missing_index_repair(exc)
        raise
