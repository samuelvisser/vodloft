from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from backend.types.local_media_profile_types import PREFERRED_FORMAT_HEIGHTS
from backend.utils.keyed_locks import KeyedLocks
from config import get_settings
from config.network import NO_INTERNET_CONNECTION_MESSAGE, message_indicates_no_internet
from sources import Site


logger = logging.getLogger(__name__)


class VideoCacheError(Exception):
    """The cache could not prepare a video; ``status_code`` says whose fault it is."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail

_VIDEO_CACHE_DIRECTORY = "video"
_ARTWORK_CACHE_DIRECTORY = "artwork"
_CACHE_LOCKS: KeyedLocks[Path] = KeyedLocks()


def _video_cache_root() -> Path:
    return Path(get_settings().download_settings.stream_cache_root) / _VIDEO_CACHE_DIRECTORY


def artwork_cache_path(url: str, image_format: str) -> Path:
    """Where the cache keeps a picture from ``url``, for a WebDAV share that lists it."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return Path(get_settings().download_settings.stream_cache_root) / _ARTWORK_CACHE_DIRECTORY / f"{digest}.{image_format}"


def _cache_retention_seconds() -> int:
    return get_settings().download_settings.stream_cache_retention_seconds


def _cache_path(episode_uuid: str) -> Path:
    digest = hashlib.sha256(episode_uuid.encode("utf-8")).hexdigest()
    return _video_cache_root() / f"{digest}.mp4"


def mp4_cache_path(key: str) -> Path:
    """Where the Stream Video Cache keeps the MP4 file of ``key``, such as an episode's UUID."""
    return _cache_path(key)


def stream_height(site: Site, preferred_format_height: int | None) -> int | None:
    """The resolution a feed streams the Site's video at: the highest it has up to the feed's format."""
    heights = sorted(site.stream_video_heights)
    if not heights:
        return None
    if preferred_format_height is None:
        return heights[-1]
    return max((height for height in heights if height <= preferred_format_height), default=heights[0])


def joins_mp4(site: Site, height: int | None) -> bool:
    """Whether a feed's MP4 at this resolution is joined from the Site's tracks."""
    return site.stream_file_height is not None and height is not None and height != site.stream_file_height


def joined_key(episode_uuid: str, height: int) -> str:
    return f"{episode_uuid}-{height}p"


def episode_mp4_key(site: Site, preferred_format: str, episode_uuid: str) -> str:
    """Under which key the cache keeps the episode's MP4 for a profile of this format: joined from the Site's
    tracks at the profile's resolution, or else the Site's own video as one file."""
    height = stream_height(site, PREFERRED_FORMAT_HEIGHTS.get(preferred_format))
    return joined_key(episode_uuid, height) if joins_mp4(site, height) else episode_uuid


def _last_used(stat: os.stat_result) -> float:
    return max(stat.st_atime, stat.st_mtime)


def mark_used(path: Path) -> None:
    """Keep a cached file for another retention period from now.

    Only its access time moves: its modification time stays the same, so the Last-Modified and ETag
    a podcast app gets for it do too. An app that asks for a range with If-Range would otherwise get
    the whole file from the start, as it seems to have changed since its last request.
    """
    try:
        os.utime(path, (time.time(), path.stat().st_mtime))
    except OSError:
        pass


def _is_current(path: Path) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return False
    return stat.st_size > 0 and time.time() - _last_used(stat) < _cache_retention_seconds()


def get_cached_mp4_path(episode_uuid: str) -> Path | None:
    path = _cache_path(episode_uuid)
    return path if _is_current(path) else None


def get_cached_mp4_size(episode_uuid: str) -> int | None:
    path = get_cached_mp4_path(episode_uuid)
    if path is None:
        return None
    try:
        return path.stat().st_size
    except OSError:
        return None


def _cleanup_expired_files(root: Path, *, retention_seconds: int) -> int:
    cutoff = time.time() - retention_seconds
    try:
        paths = list(root.iterdir())
    except OSError:
        return 0

    removed = 0
    for path in paths:
        try:
            if path.is_file() and _last_used(path.stat()) <= cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def cleanup_expired_stream_cache() -> int:
    root = Path(get_settings().download_settings.stream_cache_root)
    return sum(
        _cleanup_expired_files(root / directory, retention_seconds=_cache_retention_seconds())
        for directory in (_VIDEO_CACHE_DIRECTORY, _ARTWORK_CACHE_DIRECTORY)
    )


def _ffmpeg_command(source_url: str, output_path: Path) -> list[str]:
    return [
        get_settings().download_settings.ffmpeg_path,
        "-hide_banner",
        "-loglevel", "error",
        "-nostats",
        "-nostdin",
        "-y",
        "-fflags", "+genpts",
        "-i", source_url,
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(output_path),
    ]


def prepare_cached_mp4(source_url: str, *, episode_uuid: str) -> Path:
    target = _cache_path(episode_uuid)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise VideoCacheError(503, "RSS video cache is not writable") from exc

    with _CACHE_LOCKS.hold(target):
        if _is_current(target):
            mark_used(target)
            return target

        _cleanup_expired_files(
            target.parent,
            retention_seconds=_cache_retention_seconds(),
        )
        temporary = target.with_name(f".{target.stem}.{uuid4().hex}.part")
        try:
            try:
                completed = subprocess.run(
                    _ffmpeg_command(source_url, temporary),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    errors="replace",
                    check=False,
                )
            except FileNotFoundError as exc:
                raise VideoCacheError(503, "ffmpeg is required to prepare cached RSS video") from exc
            except OSError as exc:
                raise VideoCacheError(502, "Could not prepare the video") from exc

            try:
                prepared = temporary.is_file() and temporary.stat().st_size > 0
            except OSError:
                prepared = False

            if completed.returncode != 0 or not prepared:
                stderr = completed.stderr or ""
                if message_indicates_no_internet(stderr):
                    logger.warning(NO_INTERNET_CONNECTION_MESSAGE)
                    raise VideoCacheError(503, NO_INTERNET_CONNECTION_MESSAGE)
                logger.error(
                    "ffmpeg failed to prepare cached RSS video (exit %s): %s",
                    completed.returncode,
                    stderr[-4000:],
                )
                raise VideoCacheError(502, "The video could not be prepared as MP4")

            try:
                os.replace(temporary, target)
            except OSError as exc:
                raise VideoCacheError(503, "Could not store the prepared RSS video") from exc
            return target
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
