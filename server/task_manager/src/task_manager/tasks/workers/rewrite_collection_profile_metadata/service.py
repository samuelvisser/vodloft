from __future__ import annotations

import logging

from backend.db.core import get_session
from backend.services.metadata_rewrite import (
    MetadataRewriteCounts, plan_metadata_rewrites, record_metadata_rewrite, rewrite_metadata,
)
from task_manager.scheduler.results import TaskResult
from task_manager.tasks.helpers.progress import update_progress

logger = logging.getLogger(__name__)


def run_rewrite_collection_profile_metadata(
    *, collection_id: int, local_media_profile_id: int, episode_ids: list[int] | None = None, progress=None,
) -> TaskResult:
    """Plan from a read, then rewrite each file whose metadata changes outside any transaction and record what it is
    now. Files whose metadata is already right are left as they are. With ``episode_ids``, only the files of those
    episodes."""
    update_progress(progress, 0, "Looking for files to rewrite")
    session = get_session()
    try:
        plan = plan_metadata_rewrites(
            session, collection_id=collection_id, local_media_profile_id=local_media_profile_id,
            episode_ids=episode_ids,
        )
    finally:
        session.rollback()
        session.close()

    rewrites = plan.rewrites
    counts = MetadataRewriteCounts(
        files_considered=len(rewrites) + plan.untaggable + plan.unchanged,
        files_skipped=plan.untaggable, files_unchanged=plan.unchanged,
    )
    for done, rewrite in enumerate(rewrites):
        update_progress(
            progress, round(100 * done / len(rewrites)), f"Rewriting {rewrite.media_path.name}",
            done=done, total=len(rewrites),
        )
        try:
            rewrite_metadata(rewrite)
            # Stored only now that the tags and NFO are both written: a file whose rewrite stopped halfway keeps its
            # old fingerprint, and is written again.
            record_metadata_rewrite(rewrite)
        except Exception:
            # One file that cannot be rewritten leaves the others to go on; it keeps its old metadata.
            logger.warning("Could not rewrite the metadata of %s", rewrite.media_path, exc_info=True)
            counts.files_failed += 1
            continue
        counts.files_retagged += rewrite.tags is not None
        counts.nfos_written += rewrite.nfo is not None
    summary = counts.summary()
    update_progress(progress, 100, summary, done=len(rewrites), total=len(rewrites))
    return TaskResult(summary=summary, data=counts.as_data())
