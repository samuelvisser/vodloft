"""The throttle guard: what VODLoft does when a Site throttles a download.

A throttled YouTube serves only 360p and holds back the resolutions a video has. The downloader then
refuses the file (``downloader.ThrottledError``), VODLoft records the try, and the Site's automatic downloads
wait for ``THROTTLE_PAUSE`` before the download is tried again. The try that reaches ``THROTTLED_TRIES``
keeps whatever it gets, and the upgrade check downloads a better version later.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.datetime_types import utc_datetime
from backend.db.models import Site
from backend.db.models.media_download import MediaDownloadBase, MediaDownloadHistory
from backend.services.media_access import media_site_key
from backend.services.media_download_history import record_media_download_history
from backend.types.media_download_history_types import MediaDownloadHistoryAction

THROTTLED_TRIES = 3
"""The try that keeps a throttled file, counted since the download last completed."""
THROTTLE_PAUSE = timedelta(hours=1)
"""How long a Site's automatic downloads wait after it throttled one."""


def throttled_tries(s: Session, media_download_id: int) -> int:
    """How many tries of the download were throttled since it last completed."""
    last_completed = select(func.max(MediaDownloadHistory.id)).where(
        MediaDownloadHistory.media_download_id == media_download_id,
        MediaDownloadHistory.action == MediaDownloadHistoryAction.COMPLETED.value,
    ).scalar_subquery()
    return s.scalar(select(func.count(MediaDownloadHistory.id)).where(
        MediaDownloadHistory.media_download_id == media_download_id,
        MediaDownloadHistory.action == MediaDownloadHistoryAction.THROTTLED.value,
        MediaDownloadHistory.id > func.coalesce(last_completed, 0),
    )) or 0


def refuses_throttled(s: Session, media_download_id: int) -> bool:
    """Whether the next try of the download refuses a throttled file, rather than keeping it."""
    return throttled_tries(s, media_download_id) < THROTTLED_TRIES - 1


def record_throttled(
    s: Session, media_download_id: int, *, height: int, now: datetime, metadata: dict,
) -> datetime | None:
    """Record a throttled try and pause the automatic downloads of the download's Site; until when they wait."""
    download = s.get(MediaDownloadBase, media_download_id)
    if download is None:
        return None
    until = now + THROTTLE_PAUSE
    site_key = media_site_key(download.media)
    record = s.get(Site, site_key) if site_key else None
    if record is not None:
        paused = record.downloads_paused_until
        record.downloads_paused_until = until if paused is None or utc_datetime(paused) < until else paused
    record_media_download_history(
        s, media_download_id, MediaDownloadHistoryAction.THROTTLED,
        metadata={
            **metadata, "height": height, "site": record.name if record is not None else None,
            "try": throttled_tries(s, media_download_id) + 1, "until": until.isoformat(),
        },
        occurred_at=now,
    )
    return until


def site_paused(s: Session, media_download_id: int, now: datetime) -> Site | None:
    """The download's Site, while its automatic downloads wait because it throttled one."""
    download = s.get(MediaDownloadBase, media_download_id)
    site_key = media_site_key(download.media) if download is not None else None
    record = s.get(Site, site_key) if site_key else None
    if record is None or record.downloads_paused_until is None or utc_datetime(record.downloads_paused_until) <= now:
        return None
    return record


def last_throttled(s: Session, media_download_id: int) -> bool:
    """Whether the download's last try was throttled, so it is to be tried again."""
    action = s.scalar(
        select(MediaDownloadHistory.action)
        .where(
            MediaDownloadHistory.media_download_id == media_download_id,
            MediaDownloadHistory.action.in_((
                MediaDownloadHistoryAction.THROTTLED.value, MediaDownloadHistoryAction.STARTED.value,
            )),
        )
        .order_by(MediaDownloadHistory.id.desc())
        .limit(1)
    )
    return action == MediaDownloadHistoryAction.THROTTLED.value
