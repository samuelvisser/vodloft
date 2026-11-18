"""Remove the episodes with files that a collection added from its link seasons and that no link season that is
on lists any more: their files first, each in a transaction of its own, then the episodes. One whose files are kept,
or wait for the user to say whether to keep them, stays. Also remove the reassigned episodes whose downloads in their
new collection all succeeded."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.core import run_write_transaction
from backend.db.models import Collection, Episode
from backend.db.models.media_download import EpisodeMediaDownload
from backend.services.link_seasons import held_back, leaving_outside, remove_left_episode
from backend.services.reassigned import reassignment_of, replaced_sources
from task_manager.tasks.helpers.downloads.collection_episode_downloads import (
    cancel_active_download_attempts,
    delete_episode_download_artifact,
)


def _leaving_ids(s: Session, collection_id: int) -> list[int]:
    collection = s.get(Collection, collection_id)
    if collection is None:
        return []
    return [episode.id for episode in leaving_outside(s, collection) if not held_back(episode)] + [
        episode.id for episode in replaced_sources(s, collection)
    ]


def _still_leaving(s: Session, episode: Episode) -> bool:
    # A link season may have listed it again meanwhile. A reassigned one whose old files are gone now belongs in its
    # new collection alone.
    if not episode.downloads and reassignment_of(s, episode, downloaded=False) is not None:
        return True
    return episode.id in {e.id for e in leaving_outside(s, episode.collection)} and not held_back(episode)


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
            if episode is None or not _still_leaving(w, episode):
                return False
            remove_left_episode(w, episode)
            return True

        removed += run_write_transaction(remove)
    return removed


def _delete_artifact(s: Session, download_id: int) -> None:
    download = s.get(EpisodeMediaDownload, download_id)
    if download is not None:
        delete_episode_download_artifact(s, download)
