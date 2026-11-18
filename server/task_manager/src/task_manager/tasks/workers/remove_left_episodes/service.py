"""Remove the episodes with files that a collection added from its link seasons and that no link season that is
on lists any more: their files first, each in a transaction of its own, then the episodes."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.core import run_write_transaction
from backend.db.models import Collection, Episode
from backend.db.models.media_download import EpisodeMediaDownload
from backend.services.link_seasons import leaving_outside, remove_left_episode
from task_manager.tasks.helpers.downloads.collection_episode_downloads import (
    cancel_active_download_attempts,
    delete_episode_download_artifact,
)


def _leaving_ids(s: Session, collection_id: int) -> list[int]:
    collection = s.get(Collection, collection_id)
    return [episode.id for episode in leaving_outside(s, collection)] if collection is not None else []


def run_remove_left_episodes(s: Session, *, collection_id: int) -> int:
    removed = 0
    for episode_id in _leaving_ids(s, collection_id):
        downloads = list(s.scalars(select(EpisodeMediaDownload).where(EpisodeMediaDownload.media_item_id == episode_id)))
        cancel_active_download_attempts(s, downloads, reason="The episode left its collection")
        for download_id in [download.id for download in downloads]:
            s.rollback()
            run_write_transaction(lambda w: _delete_artifact(w, download_id))
        s.rollback()

        def remove(w: Session) -> bool:
            episode = w.get(Episode, episode_id)
            # A link season may have listed it again meanwhile.
            if episode is None or episode.id not in {e.id for e in leaving_outside(w, episode.collection)}:
                return False
            remove_left_episode(w, episode)
            return True

        removed += run_write_transaction(remove)
    return removed


def _delete_artifact(s: Session, download_id: int) -> None:
    download = s.get(EpisodeMediaDownload, download_id)
    if download is not None:
        delete_episode_download_artifact(s, download)
