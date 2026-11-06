from __future__ import annotations

from controller.db_utils import db_session
from task_manager.scheduler.lanes import TaskLane
from task_manager.scheduler.registry import on_cron, on_event, task
from task_manager.scheduler.results import TaskResult
from .service import refresh_episode_now, run_metadata_refresh


@on_event(event_name="app.startup", resource_type="system")
@on_cron(cron="*/2 * * * *", resource_type="system", resource_id=0, coalesce=True)
@task(
    key="refresh_metadata",
    title="Refresh metadata",
    description=(
        "Looks new episodes and videos up again for a while after they are published, on their Site's schedule, "
        "so changed titles, descriptions and thumbnails reach VODLoft."
    ),
    allowed_resource_types=("system",),
    default_max_retries=0,
    tracks_progress=False,
)
async def refresh_metadata(*, resource_id: int | None = None, progress=None) -> TaskResult:
    del resource_id, progress
    with db_session() as s:
        result = run_metadata_refresh(s)
    return TaskResult(summary=result.summary(), data=result.as_data())


@task(
    key="refresh_episode_metadata",
    title="Refresh episode metadata now",
    description="Looks one episode up again right away, as Refresh now on an episode or collection asks.",
    allowed_resource_types=("episode",),
    default_max_retries=0,
    tracks_progress=False,
    executor_alias=TaskLane.METADATA,
)
async def refresh_episode_metadata(*, resource_id: int | None = None, progress=None) -> TaskResult:
    del progress
    if resource_id is None:
        raise ValueError("Refresh now needs an episode")
    with db_session() as s:
        result = refresh_episode_now(s, resource_id)
    return TaskResult(summary=result.summary(), data=result.as_data())
