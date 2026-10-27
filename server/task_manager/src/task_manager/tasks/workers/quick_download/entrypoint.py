from __future__ import annotations

from typing import Any, Optional

from task_manager.scheduler.registry import task
from task_manager.tasks.media_download_operations import on_media_download_task_terminal
from task_manager.tasks.quick_download_operations import QUICK_DOWNLOAD_TASK_KEY, recover_quick_downloads

from .service import run_quick_download


@task(
    key=QUICK_DOWNLOAD_TASK_KEY,
    title="Quick download",
    description="Fetches and converts one file for a browser download, outside the library.",
    allowed_resource_types=("quick_download",),
    default_max_retries=1,
    tracks_progress=True,
    executor_alias="downloads",
    terminal_callback=on_media_download_task_terminal,
    recovery_dispatcher=recover_quick_downloads,
)
async def quick_download(
    *,
    resource_id: Optional[int] = None,
    request: dict[str, Any],
    progress=None,
):
    return run_quick_download(request, progress=progress)
