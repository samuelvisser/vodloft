from __future__ import annotations

from controller.db_utils import db_session
from task_manager.scheduler.registry import on_cron, on_event, task
from task_manager.scheduler.results import TaskResult
from .pending_checks import run_pending_checks


@on_event(event_name="app.startup", resource_type="system")
@on_cron(cron="*/2 * * * *", resource_type="system", resource_id=0, coalesce=True)
@task(
    key="check_pending_episodes",
    title="Check upcoming and live episodes",
    description=(
        "Looks upcoming and live episodes up again until they are published: every hour, often from 15 minutes "
        "before they start, and every few minutes while they are live. Each Site can change how often."
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
