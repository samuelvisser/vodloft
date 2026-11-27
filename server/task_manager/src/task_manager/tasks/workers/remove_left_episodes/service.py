"""Remove the episodes with files that a collection added from its link seasons and that no link season that is
on lists any more: their files first, each in a transaction of its own, then the episodes. One whose files are kept,
or wait for the user to say whether to keep them, stays. So do the episodes of a feed the collection no longer takes."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.core import run_write_transaction
from backend.db.models import Collection, Episode
from backend.db.models.media_download import EpisodeMediaDownload
from backend.services.link_seasons import held_back, leaving_outside, remove_left_episode
from backend.services.season_order import arrange_seasons
from task_manager.tasks.helpers.progress import update_progress
from task_manager.tasks.helpers.downloads.collection_episode_downloads import (
    cancel_active_download_attempts,
    delete_episode_download_artifact,
)


def _leaving_ids(s: Session, collection_id: int) -> list[int]:
    collection = s.get(Collection, collection_id)
    if collection is None:
        return []
    return [episode.id for episode in leaving_outside(s, collection) if not held_back(episode)]


def _still_leaving(s: Session, episode: Episode) -> bool:
    # A link season may have listed it again meanwhile.
    return episode.id in {e.id for e in leaving_outside(s, episode.collection)} and not held_back(episode)


def episode_words(s: Session, collection_id: int):
    """What the collection calls its episodes, as ``Names``; None when it is gone."""
    from backend.services.sites import collection_words

    collection = s.get(Collection, collection_id)
    return collection_words(collection).episode if collection is not None else None


def run_remove_left_episodes(s: Session, *, collection_id: int, progress=None) -> int:
    removed = 0
    leaving = _leaving_ids(s, collection_id)
    s.rollback()
    words = episode_words(s, collection_id)
    s.rollback()
    for position, episode_id in enumerate(leaving):
        # Stops here when the user cancels or a save of the collection's seasons replaces it, between two episodes.
        update_progress(
            progress, position * 100 // len(leaving), f"Removing {len(leaving)} {words.plural} and their files",
            done=position, total=len(leaving),
        )
        episode = s.get(Episode, episode_id)
        if episode is None or not _still_leaving(s, episode):
            # A list took it again meanwhile, or the user keeps its files now: its files stay.
            s.rollback()
            continue
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
    if removed:
        # The seasons they emptied went; the others are numbered again, as when videos without files leave.
        run_write_transaction(lambda w: _arrange(w, collection_id))
    return removed


def _arrange(s: Session, collection_id: int) -> None:
    collection = s.get(Collection, collection_id)
    if collection is not None:
        arrange_seasons(s, collection)


def _delete_artifact(s: Session, download_id: int) -> None:
    download = s.get(EpisodeMediaDownload, download_id)
    if download is not None:
        delete_episode_download_artifact(s, download)
