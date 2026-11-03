from __future__ import annotations

from controller.db_utils import db_session
from task_manager.scheduler.registry import on_cron, task
from task_manager.scheduler.results import TaskResult

from .service import run_upgrade_checks


@on_cron(
    # Each download's check is due days after it was downloaded; an hourly look is plenty.
    cron="17 * * * *",
    resource_type="system",
    resource_id=0,
    coalesce=True,
)
@task(
    key="upgrade_check",
    title="Check for better versions",
    description="Downloads episodes again when a Download Profile's upgrade check finds a better version.",
    allowed_resource_types=("system",),
    default_max_retries=1,
    tracks_progress=False,
)
async def upgrade_check(*, resource_id: int | None = None, progress=None) -> TaskResult:
    del resource_id, progress
    with db_session() as s:
        return run_upgrade_checks(s)
