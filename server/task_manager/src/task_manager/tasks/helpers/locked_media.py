"""Media that needed an access VODLoft lacked, once its Source says it no longer does.

The scans and the metadata refresh see whether anyone may watch a video now,
and the checks of locked media ask the Source about each one. Whichever finds a
video open lets go of its lock and downloads it again when it was refused.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db.models import Episode
from backend.db.models.media_item import MediaItemBase
from backend.services.media_access import unlock
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from task_manager.events.transactional import queue_event
from task_manager.scheduler.types import OperationSource
from task_manager.tasks.media_download_operations import (
    create_media_download_operation,
    get_active_media_download_operation,
)
from task_manager.tasks.workers.download_profile_worker.event_adapter import DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT


def open_up(s: Session, media: MediaItemBase) -> bool:
    """The Source says anyone may watch the media now. Returns whether it had been refused, and so is
    downloaded again: its operations wait for ``dispatch_queued_media_download_operations``."""
    if media.access is None and media.access_refused_at is None:
        return False
    refused = media.access_refused_at is not None
    unlock(media)
    if refused:
        download_again(s, media)
    return refused


def download_again(s: Session, media: MediaItemBase) -> None:
    """Start the downloads a refusal stopped, and let Download Profiles plan an episode they skipped while it was locked."""
    for download in media.downloads:
        if (
            download.artifact_status != MediaDownloadArtifactStatus.AVAILABLE.value
            and not download.automatic_retry_suppressed
            and get_active_media_download_operation(s, download.id) is None
        ):
            create_media_download_operation(
                s, download, source=OperationSource.SYSTEM.value, prepare_existing_artifact=True,
            )
    if isinstance(media, Episode):
        queue_event(s, DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT, {"resource_type": "episode", "resource_id": media.id})
