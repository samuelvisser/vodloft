from __future__ import annotations

from task_manager.scheduler.registry import on_cron, on_event, task
from .service import run_update_source_programs


@on_event(
    event_name="app.startup",
    resource_type="system",
)
@on_cron(
    # Checked daily; each Source updates once a week.
    cron="23 4 * * *",
    resource_type="system",
    resource_id=0,
    coalesce=True,
)
@task(
    key="update_source_programs",
    title="Update yt-dlp",
    description="Keeps the programs that Sources run, such as yt-dlp, up to date with a weekly update.",
    allowed_resource_types=("system",),
    default_max_retries=3,
    tracks_progress=False,
)
async def update_source_programs(*, resource_id: int | None = None, progress=None):
    return run_update_source_programs()
