"""Streaming an episode that is not downloaded through VODLoft itself, for Sources whose URLs only work for VODLoft.

YouTube's media URLs only play to the address that looked them up and stop working after a few hours,
so a podcast app cannot be sent there. VODLoft looks the stream up when an episode is played, keeps it
until shortly before it expires, and passes the bytes on, range by range, so the app can seek.

Audio YouTube offers as M4A is passed on as it is. Other audio is transcoded to AAC on the fly. AAC in
ADTS frames, unlike an M4A file, can start anywhere, so a seek starts a new transcode at the time the
requested byte stands for, with the size of the whole stream estimated from a fixed bitrate. That
estimate is also the length the feed gives every audio episode.
"""
from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import requests
from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse

from backend.services.collection_cookies import uses_cookies
from config import get_settings
from config.network import is_no_internet_error
from sources import MediaStream, Source


logger = logging.getLogger(__name__)

AAC_BITRATE = 128_000
"""The bitrate of transcoded audio, the same as YouTube's M4A."""
# Ask for big ranges, as yt-dlp does: YouTube slows down a single request for a whole file.
_UPSTREAM_CHUNK_BYTES = 10 * 1024 * 1024
_READ_BYTES = 64 * 1024
_UPSTREAM_TIMEOUT_SECONDS = 30
# Look a stream up again this long before its URL expires, so a long episode keeps playing.
_EXPIRY_MARGIN_SECONDS = 30 * 60
# How long a stream is kept when its Source does not say when it expires.
_UNKNOWN_EXPIRY_SECONDS = 60 * 60
# How long an episode without a stream is believed: the site may well offer one at the next look.
_MISSING_SECONDS = 2 * 60
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")

_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def estimated_audio_size(duration: float | None) -> int | None:
    """The size of an episode's audio at the transcode bitrate, which YouTube's M4A also has."""
    if not duration or duration <= 0:
        return None
    return int(duration * AAC_BITRATE / 8)


@dataclass
class _Kept:
    stream: MediaStream | None
    until: float


_streams: dict[tuple[str, bool], _Kept] = {}
_locks: dict[tuple[str, bool], threading.Lock] = {}
_guard = threading.Lock()


def _lock_for(key: tuple[str, bool]) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def _kept_until(stream: MediaStream | None) -> float:
    now = time.time()
    if stream is None:
        return now + _MISSING_SECONDS
    if stream.expires_at is None:
        return now + _UNKNOWN_EXPIRY_SECONDS
    return max(now, stream.expires_at - _EXPIRY_MARGIN_SECONDS)


def _look_up(source: Source, episode, *, audio: bool) -> MediaStream | None:
    try:
        return source.media_stream(episode.sharing_url, audio=audio, use_cookies=uses_cookies(episode.collection))
    except Exception as exc:
        if is_no_internet_error(exc):
            raise
        logger.warning("Could not look up the %s stream of %s: %s", source.name, episode.sharing_url, exc)
        raise HTTPException(status_code=502, detail=f"{source.name} stream is currently unavailable") from exc


def episode_stream(source: Source, episode, *, audio: bool, fresh: bool = False) -> MediaStream | None:
    """The episode's stream, looked up once and kept until shortly before it expires.

    ``fresh`` looks it up again, for a URL the site stopped accepting.
    """
    key = (episode.uuid, audio)
    with _lock_for(key):
        kept = _streams.get(key)
        if kept is not None and not fresh and kept.until > time.time():
            return kept.stream
        stream = _look_up(source, episode, audio=audio)
        _streams[key] = _Kept(stream, _kept_until(stream))
        # Drop what expired, so the cache does not grow with every episode ever played.
        now = time.time()
        for other in [other for other, value in _streams.items() if value.until <= now]:
            _streams.pop(other, None)
        return stream


def _requested_range(header: str | None, size: int | None) -> tuple[int, int | None] | None:
    """The first and last byte a Range header asks for, or None for the whole stream."""
    if not header:
        return None
    match = _RANGE.match(header.strip())
    if match is None:
        raise HTTPException(status_code=416, detail="Only a single byte range is supported")
    first, last = match.groups()
    if not first:
        if not last or size is None:
            raise HTTPException(status_code=416, detail="Range not satisfiable")
        suffix = int(last)
        return max(0, size - suffix), size - 1
    start = int(first)
    end = int(last) if last else None
    if size is not None:
        if start >= size:
            raise HTTPException(status_code=416, detail="Range not satisfiable", headers={"Content-Range": f"bytes */{size}"})
        end = size - 1 if end is None else min(end, size - 1)
    if end is not None and end < start:
        raise HTTPException(status_code=416, detail="Range not satisfiable")
    return start, end


def _upstream(stream: MediaStream, start: int, end: int | None) -> requests.Response:
    last = start + _UPSTREAM_CHUNK_BYTES - 1
    if end is not None:
        last = min(last, end)
    return requests.get(
        stream.url, headers={**stream.headers, "Range": f"bytes={start}-{last}"},
        stream=True, timeout=_UPSTREAM_TIMEOUT_SECONDS,
    )


def _total_size(response: requests.Response) -> int | None:
    total = response.headers.get("Content-Range", "").rpartition("/")[2]
    return int(total) if total.isdigit() else None


def _media_headers(*, media_type: str, filename: str, length: int | None, content_range: str | None) -> dict[str, str]:
    headers = {
        **_NO_CACHE_HEADERS,
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{filename}"',
        "Content-Type": media_type,
    }
    if length is not None:
        headers["Content-Length"] = str(length)
    if content_range is not None:
        headers["Content-Range"] = content_range
    return headers


def proxy_response(
        source: Source, episode, *, audio: bool, media_type: str, filename: str,
        range_header: str | None, head_only: bool,
) -> Response:
    """Pass the episode's own stream on, with the range the player asked for."""
    page_url = episode.sharing_url
    stream = episode_stream(source, episode, audio=audio)
    if stream is None:
        raise HTTPException(status_code=404, detail=f"No {source.name} {'audio' if audio else 'video'} stream for this episode")
    if not stream.ready:
        return transcode_response(
            stream, duration=episode.duration, filename=filename, range_header=range_header, head_only=head_only,
        )

    wanted = _requested_range(range_header, stream.size_bytes)
    start, end = wanted if wanted is not None else (0, None)
    if head_only and stream.size_bytes is not None:
        size = stream.size_bytes
        last = size - 1 if end is None else end
        return Response(status_code=206 if wanted else 200, headers=_media_headers(
            media_type=media_type, filename=filename, length=last - start + 1,
            content_range=f"bytes {start}-{last}/{size}" if wanted else None,
        ))

    first = _upstream(stream, start, end)
    if first.status_code == 403:
        # The URL expired early or no longer plays to this address: look it up once more.
        first.close()
        stream = episode_stream(source, episode, audio=audio, fresh=True)
        if stream is None:
            raise HTTPException(status_code=404, detail=f"No {source.name} stream for this episode")
        first = _upstream(stream, start, end)
    if first.status_code == 416:
        first.close()
        raise HTTPException(status_code=416, detail="Range not satisfiable")
    if first.status_code not in (200, 206):
        first.close()
        logger.warning("%s answered %s for a stream of %s", source.name, first.status_code, page_url)
        raise HTTPException(status_code=502, detail=f"{source.name} stream is currently unavailable")

    size = _total_size(first) or stream.size_bytes
    last = end if end is not None else (size - 1 if size is not None else None)
    length = last - start + 1 if last is not None else None
    headers = _media_headers(
        media_type=media_type, filename=filename, length=length,
        content_range=f"bytes {start}-{last}/{size}" if wanted is not None and last is not None and size else None,
    )
    if head_only:
        first.close()
        return Response(status_code=206 if wanted else 200, headers=headers)

    def body() -> Iterator[bytes]:
        response = first
        position = start
        try:
            while True:
                for chunk in response.iter_content(_READ_BYTES):
                    if last is not None and position + len(chunk) > last + 1:
                        chunk = chunk[:last + 1 - position]
                    position += len(chunk)
                    if chunk:
                        yield chunk
                    if last is not None and position > last:
                        return
                response.close()
                if response.status_code == 200 or (last is None and size is None):
                    return  # The site sent the whole stream at once.
                if (last is not None and position > last) or (size is not None and position >= size):
                    return
                response = _upstream(stream, position, last)
                if response.status_code not in (200, 206):
                    logger.warning("%s stopped a stream of %s with %s", source.name, page_url, response.status_code)
                    return
        finally:
            response.close()

    return StreamingResponse(body(), status_code=206 if wanted is not None else 200, headers=headers)


def _ffmpeg_command(stream: MediaStream, seek_seconds: float) -> list[str]:
    settings = get_settings().download_settings
    command = [settings.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if seek_seconds > 0:
        command += ["-ss", f"{seek_seconds:.3f}"]
    headers = {name: value for name, value in stream.headers.items() if name.lower() != "user-agent"}
    if "User-Agent" in stream.headers or "user-agent" in stream.headers:
        command += ["-user_agent", stream.headers.get("User-Agent") or stream.headers["user-agent"]]
    if headers:
        command += ["-headers", "".join(f"{name}: {value}\r\n" for name, value in headers.items())]
    return [
        *command, "-i", stream.url, "-vn", "-map", "0:a:0",
        "-c:a", "aac", "-b:a", str(AAC_BITRATE), "-f", "adts", "pipe:1",
    ]


def transcode_response(
        stream: MediaStream, *, duration: float | None, filename: str, range_header: str | None, head_only: bool,
) -> Response:
    """Transcode the stream to AAC while it plays, as exactly as many bytes as the estimated size."""
    size = estimated_audio_size(duration)
    wanted = _requested_range(range_header, size) if size is not None else None
    start, end = wanted if wanted is not None else (0, None)
    last = end if end is not None else (size - 1 if size is not None else None)
    length = last - start + 1 if last is not None else None
    headers = _media_headers(
        media_type="audio/aac", filename=filename.rsplit(".", 1)[0] + ".aac", length=length,
        content_range=f"bytes {start}-{last}/{size}" if wanted is not None and size is not None else None,
    )
    if size is None:
        headers.pop("Accept-Ranges")
    status_code = 206 if wanted is not None else 200
    if head_only:
        return Response(status_code=status_code, headers=headers)

    seek = start / size * duration if size and duration else 0.0
    try:
        process = subprocess.Popen(_ffmpeg_command(stream, seek), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="ffmpeg is required to stream this episode") from exc

    def body() -> Iterator[bytes]:
        sent = 0
        try:
            while length is None or sent < length:
                chunk = process.stdout.read(_READ_BYTES)
                if not chunk:
                    break
                if length is not None:
                    chunk = chunk[:length - sent]
                sent += len(chunk)
                yield chunk
            # The estimate was a little high: fill up to the size the player was told, which a decoder skips.
            while length is not None and sent < length:
                filler = b"\0" * min(_READ_BYTES, length - sent)
                sent += len(filler)
                yield filler
        finally:
            process.kill()
            process.wait()

    return StreamingResponse(body(), status_code=status_code, headers=headers)
