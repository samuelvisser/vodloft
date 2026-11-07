from __future__ import annotations

from task_manager.scheduler.registry import task
from task_manager.scheduler.results import TaskResult

from .service import run_rename_movie_profile_files


@task(
    key="rename_movie_profile_files",
    title="Rename movie profile files",
    description="Plan and safely rename every movie or video file for one Local Media Profile.",
    allowed_resource_types=("local_media_profile",),
    default_max_retries=2,
    tracks_progress=True,
)
async def rename_movie_profile_files(
        *,
        resource_id: int | None = None,
        progress=None,
) -> TaskResult:
    if resource_id is None:
        raise ValueError("Movie File Rename requires a Local Media Profile")

    return run_rename_movie_profile_files(local_media_profile_id=resource_id, progress=progress)
