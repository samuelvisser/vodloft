from __future__ import annotations

import logging

from progress_plan import PlanTracker, StageSpec

from backend.db.core import get_session, run_write_transaction
from backend.db.models import Collection
from backend.services.collection_assets import request_collection_asset_reconciliation
from backend.services.custom_indexes import request_collection_custom_index_reconciliation
from backend.services.episode_identification import change_identification, identification_steps, profile_file_steps
from backend.types.collection_types import EpisodeIdentifier, EpisodeOrder
from backend.utils.custom_index import CustomIndexNotReadyError
from task_manager.events.transactional import queue_event
from task_manager.scheduler.registry import task
from task_manager.scheduler.results import TaskResult
from task_manager.tasks.helpers.custom_index_readiness import (
    custom_index_pair_lock, pair_is_ready, request_missing_index_repair, wait_for_custom_index_pair,
)
from task_manager.tasks.helpers.progress import PlanStep, report_plan, update_progress
from task_manager.tasks.workers.rename_collection_profile_files.service import run_rename_collection_profile_files
from task_manager.tasks.workers.rewrite_collection_profile_metadata.service import run_rewrite_collection_profile_metadata

logger = logging.getLogger(__name__)

_DATA_KEYS = ("files_renamed", "files_unchanged", "files_skipped_existing", "files_retagged", "nfos_written",
              "files_skipped", "files_failed", "rename_failed")


def _plan(collection_id: int, *, renumbering: bool, profile_ids: list[int] | None = None) -> list[StageSpec]:
    """The steps of the work, or with ``profile_ids``, only the file steps of those Local Media Profiles."""
    s = get_session()
    try:
        collection = s.get(Collection, collection_id)
        if collection is None:
            return []
        if profile_ids is not None:
            return profile_file_steps(s, collection, profile_ids)
        return identification_steps(s, collection, renumbering=renumbering)
    finally:
        s.rollback()
        s.close()


@task(
    key="change_collection_identification",
    title="Change episode identification",
    description="Number a collection's episodes another way, or again after episodes moved in or out of it, then "
                "move its files to their new names and rewrite their metadata.",
    allowed_resource_types=("collection",),
    default_max_retries=0,
    tracks_progress=True,
)
async def change_collection_identification(
    *,
    resource_id: int | None = None,
    progress=None,
    episode_identifier: str | None = None,
    episode_order: str | None = None,
    renumber: bool = True,
) -> TaskResult:
    if resource_id is None or episode_identifier is None:
        raise ValueError("Changing episode identification requires a Collection and an identification")
    identification = EpisodeIdentifier(episode_identifier)
    order = EpisodeOrder(episode_order) if episode_order else None
    plan = PlanTracker(_plan(resource_id, renumbering=renumber), sink=report_plan(progress))
    # Numbering is one write that cannot say how far it is, so its step has no fraction until it is done.
    plan.start("number")

    def renumber_episodes(w):
        result = change_identification(w, resource_id, identification, episode_order=order, renumber=renumber)
        request_collection_custom_index_reconciliation(w, resource_id)
        queue_event(w, "collection.updated", {"resource_id": resource_id, "id": resource_id})
        return result

    renumbered, profile_ids = run_write_transaction(renumber_episodes)
    plan.complete("number")
    planned = {stage.id for stage in plan.snapshot().stages}
    # A profile that got files meanwhile has steps of its own now.
    added = [profile_id for profile_id in profile_ids if f"rename:{profile_id}" not in planned]
    if added:
        plan.add(*_plan(resource_id, renumbering=renumber, profile_ids=added))

    totals = dict.fromkeys(_DATA_KEYS, 0)
    for profile_id in profile_ids:
        try:
            while True:
                await wait_for_custom_index_pair(resource_id, profile_id)
                async with custom_index_pair_lock(resource_id, profile_id):
                    if not pair_is_ready(resource_id, profile_id):
                        continue
                    plan.start(f"rename:{profile_id}")
                    try:
                        renamed = run_rename_collection_profile_files(
                            collection_id=resource_id, local_media_profile_id=profile_id,
                            progress=PlanStep(plan, progress, f"rename:{profile_id}"),
                        )
                    except (OSError, ValueError):
                        # The episodes have their new numbers already: a file that cannot move, such as one that
                        # went missing, keeps its name, and Rename files can move it later.
                        logger.warning("Could not rename the files of Local Media Profile %s", profile_id, exc_info=True)
                        renamed = TaskResult(summary="Could not rename the files", data={"rename_failed": 1})
                        plan.fail(f"rename:{profile_id}")
                    plan.complete(f"rename:{profile_id}")
                    plan.start(f"rewrite:{profile_id}")
                    rewritten = run_rewrite_collection_profile_metadata(
                        collection_id=resource_id, local_media_profile_id=profile_id,
                        progress=PlanStep(plan, progress, f"rewrite:{profile_id}"),
                    )
                    plan.complete(f"rewrite:{profile_id}")
                    break
        except CustomIndexNotReadyError as exc:
            request_missing_index_repair(exc)
            raise
        for result in (renamed, rewritten):
            for key in _DATA_KEYS:
                totals[key] += int((result.data or {}).get(key, 0))
    # A profile whose files went before the numbering has nothing to do.
    for stage in plan.snapshot().stages:
        if stage.state == "pending":
            plan.skip(stage.id)
    if profile_ids:
        run_write_transaction(lambda w: request_collection_asset_reconciliation(w, resource_id))

    summary = f"Numbered {renumbered} episode(s) again"
    if profile_ids:
        summary += f", renamed {totals['files_renamed']} file(s)"
        if totals["files_retagged"]:
            summary += f", updated the tags of {totals['files_retagged']} file(s)"
        if totals["nfos_written"]:
            summary += f", wrote {totals['nfos_written']} NFO file(s)"
        if totals["rename_failed"]:
            summary += f"; the files of {totals['rename_failed']} Local Media Profile(s) could not all be renamed"
        if totals["files_failed"]:
            summary += f"; {totals['files_failed']} file(s) kept their old metadata"
    update_progress(progress, 100, summary)
    return TaskResult(summary=summary, data={"episodes_renumbered": renumbered, **totals})
