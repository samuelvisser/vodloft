"""Let Apple's players play Daily Wire HLS downloads.

The playlist of a Daily Wire HLS download named the subtitle group of The Daily Wire's own playlist on
each resolution, but the download does not keep the subtitles. Apple's players refuse a playlist that
names a group it does not define, so podcast apps said playback failed. New downloads leave those names
out; the playlists of downloads made before are rewritten without them.

Revision ID: 17506d02e509
Revises: a1af462faa04
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from sqlalchemy import select

from backend.db.core import get_session, run_write_transaction
from backend.db.models.media_download.MediaDownloadBase import MediaDownloadBase
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from downloader.hls import parse_attribute_list
from downloader.storage.identity import inspect_artifact


revision = "17506d02e509"
down_revision = "a1af462faa04"
title = "Let Apple's players play Daily Wire HLS downloads"

logger = logging.getLogger(__name__)

_TITLE = "Repairing HLS playlists"
_BATCH = 50
_GROUP_ATTRIBUTE_RE = re.compile(r',(AUDIO|VIDEO|SUBTITLES|CLOSED-CAPTIONS)="([^"]*)"')


def _bundles() -> list[tuple[int, str]]:
    """Every available HLS download, with its playlist."""
    session = get_session()
    try:
        return list(session.execute(
            select(MediaDownloadBase.id, MediaDownloadBase.file_path)
            .where(
                MediaDownloadBase.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value,
                MediaDownloadBase.file_path.like("%.m3u8"),
            )
            .order_by(MediaDownloadBase.id)
        ).tuples())
    finally:
        session.close()


def _without_unknown_groups(text: str) -> str:
    """The playlist without the names of groups its variants use but it does not define."""
    defined = set()
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXT-X-MEDIA:"):
            attributes = parse_attribute_list(line.split(":", 1)[1])
            defined.add((attributes.get("TYPE"), attributes.get("GROUP-ID")))

    def keep(match: re.Match) -> str:
        return match.group(0) if (match.group(1), match.group(2)) in defined else ""

    return "\n".join(
        _GROUP_ATTRIBUTE_RE.sub(keep, line) if line.startswith("#EXT-X-STREAM-INF:") else line
        for line in text.split("\n")
    )


def _repair(master_path: str) -> bool:
    """Leave out the groups the playlist names but does not define. Whether it changed."""
    try:
        with Path(master_path).open("r+", encoding="utf-8", newline="") as file:
            text = file.read()
            repaired = _without_unknown_groups(text)
            if repaired == text:
                return False
            # Written over in place, so the download keeps its file.
            file.seek(0)
            file.write(repaired)
            file.truncate()
    except (OSError, UnicodeError) as exc:
        logger.warning("Could not repair the HLS playlist %s: %s", master_path, exc)
        return False
    return True


def _repair_all(bundles: list[tuple[int, str]]) -> dict[int, object]:
    """Repair each playlist, and read the identity of the ones that changed."""
    identities = {}
    for download_id, master in bundles:
        if master and _repair(master):
            try:
                identities[download_id] = inspect_artifact(master)
            except (OSError, ValueError):
                continue
    return identities


def _remember(identities: dict[int, object]) -> None:
    """Store the new size and fingerprint of rewritten playlists, so they are still known as the downloads."""
    def work(session):
        for download in session.scalars(select(MediaDownloadBase).where(MediaDownloadBase.id.in_(identities))):
            identity = identities[download.id]
            download.artifact_stat_dev = identity.stat_dev
            download.artifact_stat_ino = identity.stat_ino
            download.artifact_size_bytes = identity.size_bytes
            download.artifact_fingerprint = identity.fingerprint

    run_write_transaction(work)


async def migrate(context) -> None:
    bundles = _bundles()
    if not bundles:
        return
    total = len(bundles)
    context.update_progress(0, total, _TITLE)
    repaired = 0
    for start in range(0, total, _BATCH):
        context.raise_if_canceled()
        identities = await asyncio.to_thread(_repair_all, bundles[start:start + _BATCH])
        if identities:
            _remember(identities)
            repaired += len(identities)
        context.update_progress(min(start + _BATCH, total), total, _TITLE)
    if repaired:
        logger.info("Left unknown groups out of %s HLS playlists for Apple's players", repaired)
