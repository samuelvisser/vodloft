from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.core import run_write_transaction
from backend.db.models import Episode, Video
from backend.db.models.media_item import MediaItemBase
from backend.services.media_access import media_locked, record_check
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from config.network import is_no_internet_error
from sources import UnknownSourceError, get_source
from task_manager.events.transactional import queue_event
from task_manager.scheduler.results import TaskResult
from task_manager.scheduler.types import OperationSource
from task_manager.tasks.media_download_operations import (
    create_media_download_operation,
    dispatch_queued_media_download_operations,
    get_active_media_download_operation,
)
from task_manager.tasks.workers.download_profile_worker.event_adapter import DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT

logger = logging.getLogger(__name__)

_CHECKS_PER_RUN = 25
"""Each check asks the site about one video; the rest wait for the next hourly run."""
_RETRY_AFTER = timedelta(days=1)
"""A check that could not ask the site tries again this much later."""


def run_access_checks(s: Session, *, now: datetime | None = None) -> TaskResult:
    """Check the locked media whose check is due, and download again what opened up."""
    now = now or datetime.now(timezone.utc)
    due = list(s.scalars(
        select(MediaItemBase.id)
        .where(MediaItemBase.access_check_at.is_not(None), MediaItemBase.access_check_at <= now)
        .order_by(MediaItemBase.access_check_at)
        .limit(_CHECKS_PER_RUN)
    ))
    s.rollback()
    checked = opened = 0
    for media_id in due:
        result = _check(s, media_id, now)
        if result is not None:
            checked += 1
            opened += result
    run_write_transaction(dispatch_queued_media_download_operations)
    return TaskResult(
        summary=f"Checked {checked} locked video(s), {opened} can be downloaded" if checked else "No locked videos were due",
        data={"checked": checked, "opened": opened},
    )


def _check(s: Session, media_id: int, now: datetime) -> bool | None:
    """Ask the Source about one media item, then store what it said in a short write.

    Returns whether a download starts, or None when nothing was checked.
    """
    media = s.get(MediaItemBase, media_id)
    if not isinstance(media, (Episode, Video)):
        s.rollback()
        _check_later(media_id, None)
        return None
    slug = media.source_slug if isinstance(media, Episode) else media.slug
    url, source_key = media.sharing_url, media.source_key
    s.rollback()
    try:
        access = get_source(source_key).current_access(slug=slug, url=url)
    except UnknownSourceError:
        _check_later(media_id, None)
        return None
    except Exception as exc:
        if is_no_internet_error(exc):
            raise
        logger.info("Could not check whether %s can be downloaded: %s", url, exc)
        _check_later(media_id, now + _RETRY_AFTER)
        return None
    return run_write_transaction(lambda w: _record(w, media_id, access, now))


def _check_later(media_id: int, when: datetime | None) -> None:
    def work(w: Session) -> None:
        media = w.get(MediaItemBase, media_id)
        if media is not None:
            media.access_check_at = when

    run_write_transaction(work)


def _record(s: Session, media_id: int, access: str | None, now: datetime) -> bool:
    media = s.get(MediaItemBase, media_id)
    if media is None:
        return False
    record_check(media, access, now=now)
    if media_locked(media):
        return False
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
        # A Download Profile that skipped the episode while it was locked plans it now.
        queue_event(s, DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT, {"resource_type": "episode", "resource_id": media.id})
    return True
