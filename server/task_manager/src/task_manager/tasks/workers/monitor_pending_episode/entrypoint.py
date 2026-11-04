from __future__ import annotations

from typing import Optional

from controller.db_utils import db_session
from task_manager.scheduler.registry import on_cron, on_event, task
from task_manager.scheduler.results import TaskResult
from .pending_checks import run_pending_checks
from .service import run_monitor_pending_episode


@task(
    key="monitor_pending_episode",
    title="Monitor pending episode",
    description="Monitor a scheduled, delayed, live, processing or countdown episode until ownership transfers.",
    allowed_resource_types=("episode",),
    default_max_retries=5,
    tracks_progress=False,
)
async def monitor_pending_episode(
    *,
    resource_id: Optional[int] = None,
    slug: Optional[str] = None,
    progress=None,
    collection_slug: Optional[str] = None,
    collection_id: Optional[int] = None,
    season_id: Optional[int] = None,
    episode_identifier: Optional[str] = None,
    episode_index: Optional[int] = None,
) -> None:
    del progress
    with db_session() as s:
        await run_monitor_pending_episode(
            s,
            episode_id=resource_id,
            episode_slug=slug,
            collection_id=collection_id,
            collection_slug=collection_slug,
            season_id=season_id,
            episode_identifier=episode_identifier,
            episode_index=episode_index,
        )


@on_event(event_name="app.startup", resource_type="system")
@on_cron(cron="*/2 * * * *", resource_type="system", resource_id=0, coalesce=True)
@task(
    key="check_pending_episodes",
    title="Check upcoming and live episodes",
    description=(
        "Looks upcoming and live YouTube videos and other uploads up again until they are published: every hour, "
        "and often from 15 minutes before they start."
    ),
    allowed_resource_types=("system",),
    default_max_retries=0,
    tracks_progress=False,
)
async def check_pending_episodes(*, resource_id: int | None = None, progress=None) -> TaskResult:
    del resource_id, progress
    with db_session() as s:
        result = run_pending_checks(s)
    return TaskResult(summary=result.summary(), data=result.as_data())
