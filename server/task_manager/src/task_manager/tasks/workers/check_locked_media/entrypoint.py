from __future__ import annotations

from controller.db_utils import db_session
from task_manager.scheduler.registry import on_cron, task
from task_manager.scheduler.results import TaskResult

from .service import run_access_checks


@on_cron(
    # A locked video's checks are days apart; an hourly look is plenty.
    cron="43 * * * *",
    resource_type="system",
    resource_id=0,
    coalesce=True,
)
@task(
    key="check_locked_media",
    title="Check locked videos",
    description="Asks the site whether videos VODLoft could not download for lack of access can be downloaded now.",
    allowed_resource_types=("system",),
    default_max_retries=1,
    tracks_progress=False,
)
async def check_locked_media(*, resource_id: int | None = None, progress=None) -> TaskResult:
    del resource_id, progress
    with db_session() as s:
        return run_access_checks(s)
