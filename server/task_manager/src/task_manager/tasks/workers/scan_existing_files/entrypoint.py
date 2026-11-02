from __future__ import annotations

import asyncio

from controller.db_utils import db_session
from task_manager.scheduler.registry import task
from task_manager.scheduler.results import TaskResult


def _run(collection_id: int, local_media_profile_id: int | None) -> TaskResult:
    from backend.services.existing_files import run_scan

    with db_session() as session:
        profile_ids = [local_media_profile_id] if local_media_profile_id is not None else []
        totals: dict[str, int] = {}
        for profile_id in profile_ids:
            for key, value in run_scan(session, collection_id=collection_id, local_media_profile_id=profile_id).items():
                totals[key] = totals.get(key, 0) + value
    files = totals.get("files", 0)
    summary = (
        f"Found {files} existing file(s): {totals.get('certain', 0)} certain, "
        f"{totals.get('likely', 0)} likely, {totals.get('review', 0)} to check"
        if profile_ids else "No existing files were waiting to be matched"
    )
    return TaskResult(summary=summary, data=totals)


@task(
    key="scan_existing_files",
    title="Match existing files",
    description="Find the media files already in a folder and match them to the collection's episodes.",
    allowed_resource_types=("collection",),
    default_max_retries=0,
)
async def scan_existing_files(
    *, resource_id: int | None = None, local_media_profile_id: int | None = None, **_kwargs,
) -> TaskResult:
    if resource_id is None:
        raise ValueError("Matching existing files needs a Collection")
    return await asyncio.to_thread(_run, resource_id, local_media_profile_id)
