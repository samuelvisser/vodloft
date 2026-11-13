"""Keep Apple's players playing HLS downloads with subtitles.

The subtitles kept in an HLS download were one WebVTT part as long as the whole video, and Apple's
players stopped playing such a download a few minutes in. New downloads split them into parts as long
as the video's; the subtitles of downloads made before are split the same way.

Revision ID: 875ce72375ca
Revises: 17506d02e509
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from backend.db.core import get_session
from backend.db.models.media_download.MediaDownloadBase import MediaDownloadBase
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from downloader import hls_asset_root
from downloader.hls_bundle import write_hls_subtitle_segments


revision = "875ce72375ca"
down_revision = "17506d02e509"
title = "Keep Apple's players playing HLS downloads with subtitles"

logger = logging.getLogger(__name__)

_TITLE = "Splitting HLS subtitles"
_BATCH = 50
_WHOLE_FILE = "subtitles.vtt"


def _bundles() -> list[str]:
    """The playlist of every available HLS download."""
    session = get_session()
    try:
        return list(session.scalars(
            select(MediaDownloadBase.file_path)
            .where(
                MediaDownloadBase.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value,
                MediaDownloadBase.file_path.like("%.m3u8"),
            )
            .order_by(MediaDownloadBase.id)
        ))
    finally:
        session.close()


def _seconds(playlist: Path, tag: str) -> list[float]:
    values = []
    for line in playlist.read_text(encoding="utf-8").splitlines():
        if line.startswith(tag):
            values.append(float(line.split(":", 1)[1].split(",", 1)[0]))
    return values


def _split(master_path: str) -> int:
    """Split the bundle's whole-video subtitles into parts. How many subtitles it split."""
    root = hls_asset_root(master_path)
    videos = sorted(root.glob("*p/playlist.m3u8"))
    if not videos:
        return 0
    try:
        target = _seconds(videos[0], "#EXT-X-TARGETDURATION:")
        segment_seconds = max(1, int(target[0])) if target else 6
    except (OSError, UnicodeError, ValueError):
        segment_seconds = 6
    split = 0
    for whole in sorted(root.glob(f"subtitles-*/{_WHOLE_FILE}")):
        directory = whole.parent
        try:
            duration = sum(_seconds(directory / "playlist.m3u8", "#EXTINF:"))
            if duration <= 0:
                continue
            write_hls_subtitle_segments(
                whole.read_text(encoding="utf-8-sig"), directory, duration=duration, segment_seconds=segment_seconds,
            )
            whole.unlink()
        except (OSError, UnicodeError, ValueError) as exc:
            logger.warning("Could not split the HLS subtitles in %s: %s", directory, exc)
            continue
        split += 1
    return split


def _split_all(masters: list[str]) -> int:
    return sum(_split(master) for master in masters if master)


async def migrate(context) -> None:
    masters = _bundles()
    if not masters:
        return
    total = len(masters)
    context.update_progress(0, total, _TITLE)
    split = 0
    for start in range(0, total, _BATCH):
        context.raise_if_canceled()
        split += await asyncio.to_thread(_split_all, masters[start:start + _BATCH])
        context.update_progress(min(start + _BATCH, total), total, _TITLE)
    if split:
        logger.info("Split the subtitles of HLS downloads into parts %s times for Apple's players", split)
