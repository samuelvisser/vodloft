"""Let Apple's players show the video of HLS downloads that VODLoft split itself.

VODLoft splits the separate video and audio files a Site such as YouTube has into HLS parts. Until
now each part's header kept an edit list that begins with an empty edit, as the first frame of a
YouTube video does not start at 0. Apple's players, and the podcast apps that use them, then play the
sound of such a download but show no picture. New downloads get no edit list. The ones already
downloaded keep theirs, but each such edit list is turned into a box that players skip: only its
four-letter name changes, so the file keeps its size and every part stays where its playlist says.

Revision ID: a1af462faa04
Revises: 536d9eeb6f76
"""

from __future__ import annotations

import asyncio
import logging
import struct
from pathlib import Path

from sqlalchemy import select

from backend.db.core import get_session
from backend.db.models.media_download.MediaDownloadBase import MediaDownloadBase
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from downloader import hls_asset_root
from downloader.hls import parse_attribute_list


revision = "a1af462faa04"
down_revision = "536d9eeb6f76"
title = "Show the video of HLS downloads in Apple's players"

logger = logging.getLogger(__name__)

_TITLE = "Repairing HLS downloads"
_CONTAINERS = {b"moov", b"trak"}
_HEADER_LIMIT = 1024 * 1024
"""A part's header, before its first frame, is a few kilobytes; a larger one is not VODLoft's."""


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


def _boxes(data: bytes, start: int, end: int):
    """Each box from ``start`` to ``end``: its type, where it starts, where its content starts and where it ends."""
    position = start
    while position + 8 <= end:
        size, kind = struct.unpack(">I4s", data[position:position + 8])
        header = 8
        if size == 1:
            if position + 16 > end:
                return
            size = struct.unpack(">Q", data[position + 8:position + 16])[0]
            header = 16
        elif size == 0:
            size = end - position
        if size < header or position + size > end:
            return
        yield kind, position, position + header, position + size
        position += size


def _starts_empty(elst: bytes) -> bool:
    """Whether an edit list (its content) has an empty edit, one whose media time is -1."""
    if len(elst) < 8:
        return False
    version = elst[0]
    count = struct.unpack(">I", elst[4:8])[0]
    entry, time_format, time_at = (20, ">q", 8) if version == 1 else (12, ">i", 4)
    for index in range(count):
        offset = 8 + index * entry + time_at
        if offset + struct.calcsize(time_format) > len(elst):
            return False
        if struct.unpack(time_format, elst[offset:offset + struct.calcsize(time_format)])[0] == -1:
            return True
    return False


def _empty_edits(data: bytes, start: int, end: int) -> list[int]:
    """Where each edit list box ('edts') that begins with an empty edit starts."""
    found = []
    for kind, box_start, content, box_end in _boxes(data, start, end):
        if kind in _CONTAINERS:
            found += _empty_edits(data, content, box_end)
        elif kind == b"edts":
            if any(
                inner == b"elst" and _starts_empty(data[inner_content:inner_end])
                for inner, _start, inner_content, inner_end in _boxes(data, content, box_end)
            ):
                found.append(box_start)
    return found


def _header(playlist: Path) -> tuple[Path, int, int] | None:
    """The file, offset and length of the header the parts of a playlist share."""
    try:
        text = playlist.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("#EXT-X-MAP:"):
            continue
        attributes = parse_attribute_list(line.split(":", 1)[1])
        uri, byte_range = attributes.get("URI"), attributes.get("BYTERANGE")
        if not uri or not byte_range or "@" not in byte_range:
            return None
        length, offset = byte_range.split("@", 1)
        if not length.isdigit() or not offset.isdigit() or int(length) > _HEADER_LIMIT:
            return None
        return playlist.parent / uri, int(offset), int(length)
    return None


def _repair(master_path: str) -> int:
    """Turn the edit lists of the bundle's parts that begin with an empty edit into skipped boxes."""
    root = hls_asset_root(master_path)
    repaired = 0
    for playlist in sorted(root.glob("*/playlist.m3u8")):
        header = _header(playlist)
        if header is None:
            continue
        media, offset, length = header
        if not media.resolve().is_relative_to(root.resolve()):
            continue
        try:
            with media.open("r+b") as file:
                file.seek(offset)
                data = file.read(length)
                for box in _empty_edits(data, 0, len(data)):
                    file.seek(offset + box + 4)
                    file.write(b"free")
                    repaired += 1
        except OSError as exc:
            logger.warning("Could not repair the HLS download %s: %s", media, exc)
    return repaired


def _repair_all(masters: list[str]) -> int:
    return sum(_repair(master) for master in masters if master)


async def migrate(context) -> None:
    masters = _bundles()
    if not masters:
        return
    total = len(masters)
    context.update_progress(0, total, _TITLE)
    repaired = 0
    for start in range(0, total, 50):
        context.raise_if_canceled()
        repaired += await asyncio.to_thread(_repair_all, masters[start:start + 50])
        context.update_progress(min(start + 50, total), total, _TITLE)
    if repaired:
        logger.info("Let Apple's players show the video of %s HLS tracks", repaired)
