from __future__ import annotations

from controller.db_utils import db_session
from task_manager.scheduler.registry import task
from task_manager.scheduler.results import TaskResult

from .service import episode_words, run_remove_left_episodes


@task(
    key="remove_left_episodes",
    title="Remove episodes that left a collection",
    description="Deletes the files of episodes no link season of their collection lists any more, then the episodes.",
    allowed_resource_types=("collection",),
    default_max_retries=1,
)
async def remove_left_episodes(*, resource_id: int | None = None, progress=None) -> TaskResult:
    if resource_id is None:
        raise ValueError("Removing episodes that left a collection requires a collection resource")
    with db_session() as s:
        removed = run_remove_left_episodes(s, collection_id=resource_id, progress=progress)
        words = episode_words(s, resource_id)
        s.rollback()
    if words is None:
        return TaskResult(summary="The collection is gone", data={"episodes": removed})
    named = words.singular if removed == 1 else words.plural
    return TaskResult(
        summary=f"Removed {removed} {named} and {'its' if removed == 1 else 'their'} files",
        data={"episodes": removed},
    )
