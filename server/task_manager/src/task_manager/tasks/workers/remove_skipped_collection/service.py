"""Remove a collection made from one feed or list of a creator that the user took out of the library: the files of
its episodes first, each in a transaction of its own, then the collection with its episodes. The user was told the
files go with it, also the ones marked Keep."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.core import run_write_transaction
from backend.db.models import Episode
from backend.db.models.media_download import EpisodeMediaDownload
from backend.services.section_moves import drop_skipped_collection
from task_manager.tasks.helpers.downloads.collection_episode_downloads import (
    cancel_active_download_attempts,
    delete_episode_download_artifact,
)
from task_manager.tasks.helpers.progress import update_progress


def run_remove_skipped_collection(s: Session, *, collection_id: int, progress=None) -> int:
    downloads = list(s.scalars(
        select(EpisodeMediaDownload).join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
        .where(Episode.collection_id == collection_id)
    ))
    cancel_active_download_attempts(s, downloads, reason="Its collection left the library")
    ids = [download.id for download in downloads]
    s.rollback()
    for position, download_id in enumerate(ids):
        update_progress(progress, position * 100 // len(ids), f"Deleting the files of {len(ids)} download(s)")
        run_write_transaction(lambda w: _delete_artifact(w, download_id))
        s.rollback()
    run_write_transaction(lambda w: drop_skipped_collection(w, collection_id))
    return len(ids)


def _delete_artifact(s: Session, download_id: int) -> None:
    download = s.get(EpisodeMediaDownload, download_id)
    if download is not None:
        delete_episode_download_artifact(s, download)
