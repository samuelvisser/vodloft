from __future__ import annotations

import logging

from backend.db.core import get_session
from backend.services.metadata_rewrite import (
    MetadataRewriteCounts, plan_metadata_rewrites, record_metadata_rewrite, rewrite_metadata,
)
from task_manager.scheduler.results import TaskResult
from task_manager.tasks.helpers.progress import update_progress

logger = logging.getLogger(__name__)


def run_rewrite_collection_profile_metadata(*, collection_id: int, local_media_profile_id: int, progress=None) -> TaskResult:
    """Plan from a read, then rewrite each file outside any transaction and record what it is now."""
    update_progress(progress, 0, "Looking for files to rewrite")
    session = get_session()
    try:
        rewrites, untaggable = plan_metadata_rewrites(
            session, collection_id=collection_id, local_media_profile_id=local_media_profile_id,
        )
    finally:
        session.rollback()
        session.close()

    counts = MetadataRewriteCounts(files_considered=len(rewrites) + untaggable, files_skipped=untaggable)
    for done, rewrite in enumerate(rewrites):
        update_progress(progress, round(100 * done / len(rewrites)), f"Rewriting {rewrite.media_path.name}")
        try:
            rewrite_metadata(rewrite)
            record_metadata_rewrite(rewrite)
        except Exception:
            # One file that cannot be rewritten leaves the others to go on; it keeps its old metadata.
            logger.warning("Could not rewrite the metadata of %s", rewrite.media_path, exc_info=True)
            counts.files_failed += 1
            continue
        counts.files_retagged += rewrite.tags is not None
        counts.nfos_written += rewrite.nfo is not None
    summary = counts.summary()
    update_progress(progress, 100, summary)
    return TaskResult(summary=summary, data=counts.as_data())
