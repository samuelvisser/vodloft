from __future__ import annotations

from contextlib import AsyncExitStack

from sqlalchemy import update

from backend.db.models import DownloadProfile
from backend.services.collection_assets import request_collection_asset_reconciliation
from backend.services.profile_moves import move_collection_downloads
from backend.utils.custom_index import CustomIndexNotReadyError
from backend.db.core import run_write_transaction
from task_manager.scheduler.registry import task
from task_manager.scheduler.results import TaskResult
from task_manager.tasks.helpers.custom_index_readiness import (
    custom_index_pair_lock, pair_is_ready, request_missing_index_repair, wait_for_custom_index_pair,
)
from task_manager.tasks.helpers.progress import update_progress


@task(
    key="move_collection_profile_episodes",
    title="Move episodes to another profile",
    description="Move one Collection's downloads from one Local Media Profile to another, into its layout.",
    allowed_resource_types=("collection",),
    default_max_retries=2,
    tracks_progress=True,
)
async def move_collection_profile_episodes(
    *,
    resource_id: int | None = None,
    progress=None,
    source_local_media_profile_id: int | None = None,
    target_local_media_profile_id: int | None = None,
    move_download_profile: bool = False,
    held_download_profile_ids: list[int] | None = None,
) -> TaskResult:
    if resource_id is None or source_local_media_profile_id is None or target_local_media_profile_id is None:
        raise ValueError("Moving episodes requires a Collection and two Local Media Profiles")
    try:
        while True:
            await wait_for_custom_index_pair(resource_id, target_local_media_profile_id, progress=progress)
            async with AsyncExitStack() as locks:
                # Keep renames and Custom Index work for both profiles out while files move.
                for profile_id in sorted({source_local_media_profile_id, target_local_media_profile_id}):
                    await locks.enter_async_context(custom_index_pair_lock(resource_id, profile_id))
                if not pair_is_ready(resource_id, target_local_media_profile_id):
                    continue
                result = move_collection_downloads(
                    collection_id=resource_id,
                    source_id=source_local_media_profile_id,
                    target_id=target_local_media_profile_id,
                    move_download_profile=move_download_profile,
                    progress=progress,
                )
                run_write_transaction(lambda session: request_collection_asset_reconciliation(session, resource_id))
                summary = f"Moved {result.moved} episode{'s' if result.moved != 1 else ''}"
                if result.skipped:
                    summary += f"; {result.skipped} stayed where they were"
                update_progress(progress, 100, summary)
                return TaskResult(summary=summary, data=result.as_data())
    except CustomIndexNotReadyError as exc:
        request_missing_index_repair(exc)
        raise
    finally:
        if held_download_profile_ids:
            run_write_transaction(lambda session: session.execute(
                update(DownloadProfile)
                .where(DownloadProfile.id.in_(held_download_profile_ids))
                .values(enable_profile=True)
            ))
