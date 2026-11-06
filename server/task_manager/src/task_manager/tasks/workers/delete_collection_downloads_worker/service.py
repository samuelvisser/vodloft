from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.db.core import run_write_transaction
from backend.db.models.media_download import EpisodeMediaDownload
from backend.utils.episode_download_scope import EpisodeDownloadScope
from downloader import DownloadCanceled
from task_manager.tasks.helpers.download_profiles import (
    disable_download_profiles_for_episode_scope,
)
from task_manager.tasks.helpers.downloads.collection_episode_downloads import (
    cancel_active_download_attempts,
    delete_episode_download_artifact,
)
from task_manager.tasks.helpers.progress import update_progress


def run_delete_collection_downloads_worker(
        s: Session,
        *,
        collection_id: int,
        local_media_profile_id: int | None = None,
        download_profiles_disabled: int = 0,
        selected_media_download_ids: list[int] | None = None,
        progress=None,
) -> dict[str, Any]:
    """Delete existing collection artifacts; a full delete first disables the affected profiles."""
    scope = EpisodeDownloadScope.resolve(
        s,
        collection_id=collection_id,
        local_media_profile_id=local_media_profile_id,
    )
    if selected_media_download_ids is not None:
        scope = scope.select(media_download_ids=selected_media_download_ids)
    base_result = scope.result_data()
    downloads = list(scope.downloads)

    # For a full delete the API disables profiles before this worker can be
    # dispatched. Keep this idempotent guard for recovered/manual task execution
    # and commit it before cancellation helpers roll back their read transaction.
    # A partial delete (selected downloads) leaves the profiles on.
    disabled_during_worker = (
        run_write_transaction(lambda w: disable_download_profiles_for_episode_scope(w, scope))
        if selected_media_download_ids is None else 0
    )
    disabled_profile_count = max(download_profiles_disabled, disabled_during_worker)

    if not downloads:
        update_progress(progress, 100, "No downloaded episodes match this request")
        return {
            **base_result,
            "episode_files": 0,
            "download_profiles_disabled": disabled_profile_count,
        }

    total = len(downloads)
    update_progress(progress, 1, f"Preparing to delete {total} episode download(s)")

    # Any automatic work that won the profile lock before the disable is now
    # fully committed and no later profile reconciliation can create more work.
    # Cancel those existing attempts for the whole scope before removing files.
    cancel_active_download_attempts(
        s,
        downloads,
        reason="Deleted by collection download cleanup",
    )

    for index, download in enumerate(downloads, start=1):
        if progress is not None and callable(progress) and progress():
            raise DownloadCanceled("Collection download deletion was canceled")

        # Also protect against a retry started after the operation began, by the
        # user or, for a partial delete, by a Download Profile that is still on.
        cancel_active_download_attempts(
            s,
            [download],
            reason="Deleted by collection download cleanup",
        )
        # Make each destructive step durable independently. A user may cancel a
        # long-running collection cleanup without rolling already removed files back
        # into database state that claims they still exist.
        download_id = download.id
        s.rollback()
        run_write_transaction(lambda w: _delete_artifact(w, download_id))

        percentage = min(99, max(1, int(index * 100 / total)))
        update_progress(
            progress,
            percentage,
            f"Deleted {index}/{total} episode file(s)",
        )

    update_progress(progress, 100, f"Deleted {total} episode file(s)")
    return {
        **base_result,
        "episode_files": total,
        "download_profiles_disabled": disabled_profile_count,
    }


def _delete_artifact(s: Session, download_id: int) -> None:
    download = s.get(EpisodeMediaDownload, download_id)
    if download is not None:
        delete_episode_download_artifact(s, download)
