"""Asking VODLoft to check locked media again, because the user or a sign-in says access may have changed."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.core import run_write_transaction
from backend.db.models import Episode
from backend.db.models.media_item import MediaItemBase
from backend.services.media_download_history import record_media_download_history
from backend.types.media_download_history_types import MediaDownloadHistoryAction
from task_manager.events.transactional import queue_event
from task_manager.scheduler.transactional import queue_task_after_commit
from task_manager.tasks.workers.download_profile_worker.event_adapter import DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT

CHECK_TASK_KEY = "check_locked_media"


def ask_for_check(s: Session, media: Iterable[MediaItemBase], *, now: datetime | None = None) -> int:
    """Check the media again now and give each one more download, as when the user gained access.

    Returns how many were asked for.
    """
    now = now or datetime.now(timezone.utc)
    count = 0
    for item in media:
        item.access_refused_at = None
        item.access_checks = 0
        item.access_check_at = now
        for download in item.downloads:
            record_media_download_history(s, download.id, MediaDownloadHistoryAction.ACCESS_CHECK_REQUESTED)
        count += 1
    if count:
        queue_task_after_commit(s, def_key=CHECK_TASK_KEY, resource_type="system", resource_id=0)
    return count


def refused_media(s: Session, *where) -> list[MediaItemBase]:
    """The media a Source refused for lack of an access."""
    return list(s.scalars(select(MediaItemBase).where(
        MediaItemBase.access.is_not(None), MediaItemBase.access_refused_at.is_not(None), *where,
    )))


def ask_source_for_check(s: Session, source_key: str) -> int:
    """The Source's sign-in changed: check the media it refused again now."""
    return ask_for_check(s, refused_media(s, MediaItemBase.source_key == source_key))


def access_changed(source_key: str) -> int:
    """The Source's sign-in changed: check what it refused again, and plan the Collections whose
    locked episodes it may give now. Returns how many refused videos are checked again."""
    def work(s: Session) -> int:
        collection_ids = s.scalars(select(Episode.collection_id).distinct().where(
            Episode.source_key == source_key, Episode.access.is_not(None),
        ))
        for collection_id in collection_ids:
            queue_event(s, DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT, {"resource_type": "collection", "resource_id": collection_id})
        return ask_source_for_check(s, source_key)

    return run_write_transaction(work)
