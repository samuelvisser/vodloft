from __future__ import annotations

from controller.db_utils import db_session
from task_manager.scheduler.registry import on_cron, task
from task_manager.scheduler.results import TaskResult

from .service import run_follow_channels


@on_cron(
    # Once a day, after the night's re-scan of collections with quick checks.
    cron="40 5 * * *",
    resource_type="system",
    resource_id=0,
    coalesce=True,
)
@task(
    key="follow_channels",
    title="Look for new playlists and shows",
    description=(
        "Looks at each channel in the Library for playlists, shows and feeds it did not have, and adds them, "
        "ignores them or asks, as the channel is set to. Also brings each channel's name and pictures up to date."
    ),
    allowed_resource_types=("system", "channel"),
    default_max_retries=1,
    tracks_progress=False,
)
async def follow_channels(*, resource_id: int | None = None, progress=None) -> TaskResult:
    del progress
    with db_session() as s:
        # On the daily schedule the resource is the system; Check now on a channel page names the channel.
        return run_follow_channels(s, channel_id=resource_id or None)
