from __future__ import annotations

import logging

from backend.db.core import run_write_transaction
from backend.services.collection_assets import request_collection_asset_reconciliation
from backend.services.custom_indexes import request_collection_custom_index_reconciliation
from backend.services.episode_identification import change_identification
from backend.types.collection_types import EpisodeIdentifier, EpisodeOrder
from backend.utils.custom_index import CustomIndexNotReadyError
from task_manager.events.transactional import queue_event
from task_manager.scheduler.registry import task
from task_manager.scheduler.results import TaskResult
from task_manager.tasks.helpers.custom_index_readiness import (
    custom_index_pair_lock, pair_is_ready, request_missing_index_repair, wait_for_custom_index_pair,
)
from task_manager.tasks.helpers.progress import update_progress
from task_manager.tasks.workers.rename_collection_profile_files.service import run_rename_collection_profile_files
from task_manager.tasks.workers.rewrite_collection_profile_metadata.service import run_rewrite_collection_profile_metadata

logger = logging.getLogger(__name__)

# Renumbering is one quick write; the files take the rest.
_RENUMBERED_PROGRESS = 5
_DATA_KEYS = ("files_renamed", "files_unchanged", "files_skipped_existing", "files_retagged", "nfos_written",
              "files_skipped", "files_failed", "rename_failed")


class _Share:
    """Reports one step's own 0-100 progress as its share of the whole task's."""

    def __init__(self, progress, start: float, end: float):
        self._progress, self._start, self._end = progress, start, end

    def __call__(self) -> bool:
        # The renaming asks whether the task was canceled.
        return bool(self._progress()) if callable(self._progress) else False

    def set(self, percentage: int, message: str) -> None:
        update_progress(self._progress, round(self._start + (self._end - self._start) * percentage / 100), message)


@task(
    key="change_collection_identification",
    title="Change episode identification",
    description="Number a collection's episodes another way, then move its files to their new names and rewrite "
                "their metadata.",
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
) -> TaskResult:
    if resource_id is None or episode_identifier is None:
        raise ValueError("Changing episode identification requires a Collection and an identification")
    identification = EpisodeIdentifier(episode_identifier)
    order = EpisodeOrder(episode_order) if episode_order else None
    update_progress(progress, 0, "Numbering the episodes")

    def renumber(w):
        result = change_identification(w, resource_id, identification, episode_order=order)
        request_collection_custom_index_reconciliation(w, resource_id)
        queue_event(w, "collection.updated", {"resource_id": resource_id, "id": resource_id})
        return result

    renumbered, profile_ids = run_write_transaction(renumber)
    update_progress(progress, _RENUMBERED_PROGRESS, f"Numbered {renumbered} episode(s) again")

    totals = dict.fromkeys(_DATA_KEYS, 0)
    span = (100 - _RENUMBERED_PROGRESS) / max(1, len(profile_ids))
    for position, profile_id in enumerate(profile_ids):
        start = _RENUMBERED_PROGRESS + position * span
        try:
            while True:
                await wait_for_custom_index_pair(resource_id, profile_id)
                async with custom_index_pair_lock(resource_id, profile_id):
                    if not pair_is_ready(resource_id, profile_id):
                        continue
                    try:
                        renamed = run_rename_collection_profile_files(
                            collection_id=resource_id, local_media_profile_id=profile_id,
                            progress=_Share(progress, start, start + span / 2),
                        )
                    except (OSError, ValueError):
                        # The episodes have their new numbers already: a file that cannot move, such as one that
                        # went missing, keeps its name, and Rename files can move it later.
                        logger.warning("Could not rename the files of Local Media Profile %s", profile_id, exc_info=True)
                        renamed = TaskResult(summary="Could not rename the files", data={"rename_failed": 1})
                    rewritten = run_rewrite_collection_profile_metadata(
                        collection_id=resource_id, local_media_profile_id=profile_id,
                        progress=_Share(progress, start + span / 2, start + span),
                    )
                    break
        except CustomIndexNotReadyError as exc:
            request_missing_index_repair(exc)
            raise
        for result in (renamed, rewritten):
            for key in _DATA_KEYS:
                totals[key] += int((result.data or {}).get(key, 0))
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
