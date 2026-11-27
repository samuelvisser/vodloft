from __future__ import annotations

from typing import Optional

from config import get_settings
from config.settings.cron_validation import MIN_WORKER_CRON_INTERVAL_MS
from controller.db_utils import db_session
from task_manager.scheduler.registry import task, on_cron, on_event
from task_manager.scheduler.results import TaskResult
from .service import run_file_watcher


@on_event(
    event_name="app.startup",
    resource_type="collection",
)
@on_cron(
    cron=get_settings().file_watcher.scan_cron,
    enabled=get_settings().file_watcher.scan_cron_enabled,
    minimum_interval_ms=MIN_WORKER_CRON_INTERVAL_MS,
    resource_type="collection",
    resource_id=0,
    coalesce=True,
)
@task(
    key="file_watcher",
    title="Watch local files",
    description="Watch local files to keep them in sync with VODLoft database.",
    allowed_resource_types=("collection",),
    default_max_retries=5,
    tracks_progress=False,
    findings=("updated",),
)
async def file_watcher(*, resource_id: Optional[int] = None, slug: Optional[str] = None, progress=None) -> TaskResult:
    """
    Reconciles downloaded episode files on disk with the VODLoft database.

    Parameters:
    resource_id : Optional[int]
        The ID of a specific collection if the scan needs to focus on one.
    slug : Optional[str]
        The slug of a specific collection if the scan needs to focus on one.
    progress : Any
        A progress tracker object.
    """
    with db_session() as s:
        return await run_file_watcher(s, collection_id=resource_id, collection_slug=slug, progress=progress)
