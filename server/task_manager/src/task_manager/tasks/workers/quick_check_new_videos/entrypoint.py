from __future__ import annotations

from config import get_settings
from controller.db_utils import db_session
from task_manager.scheduler.registry import on_cron, on_event, task
from task_manager.scheduler.results import TaskResult
from ..fetch_new_episodes.quick_check import run_quick_check
from ..fetch_new_episodes.service import run_fetch_new_episodes


@on_event(
    event_name="app.startup",
    resource_type="system",
)
@on_cron(
    # Wakes up often; the Source decides how often each show is actually checked.
    cron=get_settings().new_episode_schedule.quick_check_cron,
    enabled=get_settings().new_episode_schedule.quick_check_cron_enabled,
    resource_type="system",
    resource_id=0,
    coalesce=True,
)
@task(
    key="quick_check_new_videos",
    title="Quick check for new videos",
    description=(
        "Checks YouTube channels and other shows with quick checks for new videos, as often as the "
        "YouTube API quota allows, and adds only what is new."
    ),
    allowed_resource_types=("system",),
    default_max_retries=0,
    tracks_progress=False,
)
async def quick_check_new_videos(*, resource_id: int | None = None, progress=None) -> TaskResult:
    with db_session() as s:
        result = run_quick_check(s)
    return TaskResult(
        summary=result.summary(),
        data={"checked": result.checked, "found": result.found, "failed": list(result.failed)},
    )


@on_cron(
    cron=get_settings().new_episode_schedule.full_rescan_cron,
    enabled=get_settings().new_episode_schedule.full_rescan_cron_enabled,
    resource_type="show",
    resource_id=0,
    coalesce=True,
)
@task(
    key="rescan_quick_checked_shows",
    title="Re-scan shows with quick checks",
    description="Lists YouTube channels and other shows with quick checks in full, to catch anything a quick check missed.",
    allowed_resource_types=("show",),
    default_max_retries=3,
    tracks_progress=False,
)
async def rescan_quick_checked_shows(*, resource_id: int | None = None, progress=None) -> TaskResult:
    with db_session() as s:
        result = await run_fetch_new_episodes(s, show_id=resource_id, quick_checked=True, progress=progress)
    return TaskResult(summary=result.summary(), data=result.as_data())
