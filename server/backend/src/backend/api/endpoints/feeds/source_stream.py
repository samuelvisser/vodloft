"""Streaming an episode that is not downloaded through VODLoft itself, for Sources whose episodes are listed.

YouTube's media URLs stop working after a few hours, so a feed cannot list them. VODLoft looks the stream
up when an episode is played and keeps it until shortly before it expires. It passes audio on, range by
range, so the app can seek, and video too unless the feed sends the app straight to the URL.

Audio YouTube offers as M4A is passed on as it is. Other audio is transcoded to AAC on the fly. AAC in
ADTS frames, unlike an M4A file, can start anywhere, so a seek starts a new transcode at the time the
requested byte stands for, with the size of the whole stream estimated from a fixed bitrate. That
estimate is also the length the feed gives every audio episode.
"""
from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Iterator

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse

from backend.services.collection_cookies import uses_cookies
from config import get_settings
from sources import MediaStream, Source

from .upstream import (
    NO_CACHE_HEADERS, READ_BYTES, LinkCache, ask_again, first_range, look_up_at_site, ranged_get, seconds_until_expiry,
    total_size,
)


logger = logging.getLogger(__name__)

AAC_BITRATE = 128_000
"""The bitrate of transcoded audio, the same as YouTube's M4A."""
# How long an episode without a stream is believed: the site may well offer one at the next look.
_MISSING_SECONDS = 2 * 60
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def estimated_audio_size(duration: float | None) -> int | None:
    """The size of an episode's audio at the transcode bitrate, which YouTube's M4A also has."""
    if not duration or duration <= 0:
        return None
    return int(duration * AAC_BITRATE / 8)


# What a feed's MP4 video takes per second with its sound, by resolution: an estimate for a file that is
# not there yet, as an app may pass over a video that says it is empty.
_VIDEO_BITRATES = ((360, 500_000), (480, 1_000_000), (720, 2_000_000), (1080, 3_000_000))
_HIGHER_VIDEO_BITRATE = 8_000_000


def estimated_video_size(duration: float | None, height: int | None) -> int | None:
    """Roughly the size of an episode's MP4 video at this resolution; 1080p when the resolution is not known."""
    if not duration or duration <= 0:
        return None
    bitrate = next((rate for most, rate in _VIDEO_BITRATES if (height or 1080) <= most), _HIGHER_VIDEO_BITRATE)
    return int(duration * bitrate / 8)


def _kept_for(stream: MediaStream | None) -> float:
    return _MISSING_SECONDS if stream is None else seconds_until_expiry([stream.expires_at])


_streams: LinkCache[tuple[str, bool], MediaStream | None] = LinkCache(_kept_for)


def episode_stream(source: Source, episode, *, audio: bool, fresh: bool = False) -> MediaStream | None:
    """The episode's stream, looked up once and kept until shortly before it expires.

    ``fresh`` looks it up again, for a URL the site stopped accepting.
    """
    url, use_cookies = episode.sharing_url, uses_cookies(episode.collection)
    return _streams.get(
        (episode.uuid, audio),
        lambda: look_up_at_site(source, "stream", url, lambda: source.media_stream(url, audio=audio, use_cookies=use_cookies)),
        fresh=fresh,
    )


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


def _media_headers(*, media_type: str, filename: str, length: int | None, content_range: str | None) -> dict[str, str]:
    headers = {
        **NO_CACHE_HEADERS,
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

    def look_up_again() -> MediaStream:
        fresh = episode_stream(source, episode, audio=audio, fresh=True)
        if fresh is None:
            raise HTTPException(status_code=404, detail=f"No {source.name} stream for this episode")
        return fresh

    stream, first = first_range(stream, start, end, look_up_again)
    if first.status_code == 416:
        first.close()
        raise HTTPException(status_code=416, detail="Range not satisfiable")
    if first.status_code not in (200, 206):
        first.close()
        logger.warning("%s answered %s for a stream of %s", source.name, first.status_code, page_url)
        raise HTTPException(status_code=502, detail=f"{source.name} stream is currently unavailable")

    size = total_size(first) or stream.size_bytes
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
                for chunk in response.iter_content(READ_BYTES):
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
                response = ask_again(stream, position, last, ranged_get(stream, position, last))
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
                chunk = process.stdout.read(READ_BYTES)
                if not chunk:
                    break
                if length is not None:
                    chunk = chunk[:length - sent]
                sent += len(chunk)
                yield chunk
            # The estimate was a little high: fill up to the size the player was told, which a decoder skips.
            while length is not None and sent < length:
                filler = b"\0" * min(READ_BYTES, length - sent)
                sent += len(filler)
                yield filler
        finally:
            process.kill()
            process.wait()

    return StreamingResponse(body(), status_code=status_code, headers=headers)
