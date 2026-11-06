"""Fill in the length of the downloads VODLoft already has.

Each download now remembers the length of its own file, so the upgrade check can tell when The Daily
Wire made an episode longer or shorter after it was downloaded. Downloads made before had no length;
it is read from their files. Downloads of the last 30 days that the upgrade check now looks at for a
different length get a check right away, so a Daily Wire episode cut down shortly before this update
is downloaded again; so does any older one whose listed length already differs from its file's.
Reading the files is why this is not part of the database migration.

Revision ID: e8ea12937f41
Revises: a3d91f5c07e2
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.db.core import get_session
from backend.db.core import run_write_transaction
from backend.db.datetime_types import utc_datetime
from backend.db.models.media_download import EpisodeMediaDownload, MediaDownloadBase
from backend.services.sites import collection_site
from backend.services.upgrade_check import check_refreshed_changes_now, checked_improvements
from backend.types.download_profile_types import MediaDownloadArtifactStatus, UpgradeImprovement
from config import get_settings
from downloader import media_duration


revision = "e8ea12937f41"
down_revision = "a3d91f5c07e2"
title = "Fill in the length of downloads"

_TITLE = "Reading the length of downloads"
_BATCH = 50
_RECENT = timedelta(days=30)


def _downloads() -> list[tuple[int, str]]:
    """Every available download without a length, with its file."""
    session = get_session()
    try:
        return list(session.execute(
            select(MediaDownloadBase.id, MediaDownloadBase.file_path)
            .where(
                MediaDownloadBase.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value,
                MediaDownloadBase.duration.is_(None),
            )
            .order_by(MediaDownloadBase.id)
        ).tuples())
    finally:
        session.close()


def _apply(lengths: dict[int, float]) -> None:
    def work(session):
        now = datetime.now(timezone.utc)
        for download in session.scalars(select(MediaDownloadBase).where(MediaDownloadBase.id.in_(lengths))):
            download.duration = lengths[download.id]
            if isinstance(download, EpisodeMediaDownload):
                episode = download.media
                site = collection_site(episode.collection)
                check_refreshed_changes_now(episode, site, now)
                profile = download.download_profile
                if (
                    profile is not None and profile.upgrade_check and download.upgrade_check_at is None
                    and UpgradeImprovement.LENGTH.value in checked_improvements(site, profile)
                    and download.downloaded_at is not None and utc_datetime(download.downloaded_at) > now - _RECENT
                ):
                    download.upgrade_check_at = now

    run_write_transaction(work)


def _lengths(files: list[tuple[int, str]], ffmpeg_path: str) -> dict[int, float]:
    found = {}
    for download_id, path in files:
        length = media_duration(path, ffmpeg_path=ffmpeg_path) if path else None
        if length:
            found[download_id] = length
    return found


async def migrate(context) -> None:
    downloads = _downloads()
    if not downloads:
        return
    ffmpeg_path = get_settings().download_settings.ffmpeg_path
    total = len(downloads)
    context.update_progress(0, total, _TITLE)
    for start in range(0, total, _BATCH):
        context.raise_if_canceled()
        batch = downloads[start:start + _BATCH]
        lengths = await asyncio.to_thread(_lengths, batch, ffmpeg_path)
        if lengths:
            _apply(lengths)
        context.update_progress(min(start + _BATCH, total), total, _TITLE)
