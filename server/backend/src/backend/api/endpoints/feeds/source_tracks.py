"""Streaming an episode from a Site that has its video and audio as separate tracks, such as YouTube.

Above the one resolution such a Site has as an MP4 file with sound (``Site.stream_file_height``), the
video has no sound, so a feed plays it in one of two ways:

* HLS: the tracks are fragmented MP4 files that start with a segment index (``sidx``). VODLoft reads
  that index and writes an HLS playlist that lists every fragment as a byte range of the Site's own
  file, with one variant per resolution and the audio as its own rendition. Nothing is joined or
  stored, so it plays at once.
* MP4: VODLoft joins video and audio into one MP4 file in the RSS cache, without re-encoding. Until it
  is ready, the episode plays the Site's MP4 file with sound. The newest episodes of a feed are joined
  as soon as the feed is fetched, so they are usually ready before anyone plays them.

The playlists list every fragment at a VODLoft address. When the feed proxies its Site's video,
VODLoft passes the bytes on; otherwise it redirects the app to the Site's file, with a link it looked
up again shortly before the old one expired. The Site's links last a few hours, and an app holds on to
a playlist far longer, so a playlist never lists them itself. The MP4 file with sound comes the same
way, straight from the Site or through VODLoft.
"""
from __future__ import annotations

import errno
import logging
import math
import os
import re
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import requests
from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse

from config import get_settings
from config.network import is_no_internet_error
from sources import MediaStream, MediaTracks, Site, Source

from .cached_video import get_cached_mp4_path, mp4_cache_path


logger = logging.getLogger(__name__)

HLS_MIME_TYPE = "application/x-mpegURL"
_UPSTREAM_CHUNK_BYTES = 10 * 1024 * 1024
_READ_BYTES = 64 * 1024
_UPSTREAM_TIMEOUT_SECONDS = 30
_EXPIRY_MARGIN_SECONDS = 30 * 60
_UNKNOWN_EXPIRY_SECONDS = 60 * 60
_MISSING_SECONDS = 2 * 60
_INDEX_FIRST_BYTES = 256 * 1024
_INDEX_MOST_BYTES = 16 * 1024 * 1024
# An episode that started playing as the Site's MP4 keeps playing as that file while an app keeps asking
# for it, so a player never gets the bytes of the joined file in the middle of the other one.
_SAME_FILE_SECONDS = 60 * 60
_JOIN_TIMEOUT_SECONDS = 3 * 60 * 60
NEWEST_EPISODES_JOINED_AHEAD = 3
_TRACK_NAME = re.compile(r"^(?:video-(\d+)|audio)\.(m3u8|mp4)$")
_RANGE = re.compile(r"^bytes=(\d+)-(\d*)$")
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


@dataclass(frozen=True)
class EpisodeRef:
    """What looking an episode up takes, kept apart from the database session that loaded it."""

    uuid: str
    url: str
    use_cookies: bool


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


# --- Looking tracks up -----------------------------------------------------------------------------

@dataclass
class _Kept:
    tracks: MediaTracks | None
    until: float


_tracks: dict[str, _Kept] = {}
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def _kept_until(tracks: MediaTracks | None) -> float:
    now = time.time()
    if tracks is None:
        return now + _MISSING_SECONDS
    expiries = [stream.expires_at for stream in (*tracks.video, tracks.audio) if stream.expires_at is not None]
    if not expiries:
        return now + _UNKNOWN_EXPIRY_SECONDS
    return max(now, min(expiries) - _EXPIRY_MARGIN_SECONDS)


def episode_tracks(source: Source, episode: EpisodeRef, *, fresh: bool = False) -> MediaTracks:
    """The episode's tracks, looked up once and kept until shortly before their links expire."""
    with _lock_for(episode.uuid):
        kept = _tracks.get(episode.uuid)
        if kept is None or fresh or kept.until <= time.time():
            try:
                found = source.media_tracks(episode.url, use_cookies=episode.use_cookies)
            except Exception as exc:
                if is_no_internet_error(exc):
                    raise
                logger.warning("Could not look up the %s tracks of %s: %s", source.name, episode.url, exc)
                raise HTTPException(status_code=502, detail=f"{source.name} stream is currently unavailable") from exc
            kept = _Kept(found, _kept_until(found))
            _tracks[episode.uuid] = kept
            now = time.time()
            for other in [other for other, value in _tracks.items() if value.until <= now]:
                _tracks.pop(other, None)
    if kept.tracks is None:
        raise HTTPException(status_code=404, detail=f"No {source.name} video tracks for this episode")
    return kept.tracks


def _video_track(tracks: MediaTracks, height: int) -> MediaStream:
    track = next((track for track in tracks.video if track.height == height), None)
    if track is None:
        raise HTTPException(status_code=404, detail=f"No {height}p video for this episode")
    return track


# --- Passing bytes on ------------------------------------------------------------------------------

def _get(stream: MediaStream, start: int, last: int) -> requests.Response:
    return requests.get(
        stream.url, headers={**stream.headers, "Range": f"bytes={start}-{last}"}, stream=True,
        timeout=_UPSTREAM_TIMEOUT_SECONDS,
    )


def _bytes_of(stream: MediaStream, start: int, end: int | None) -> Iterator[bytes]:
    """The stream's bytes from ``start`` to ``end``, asked of the Site 10 MB at a time, as it limits
    a single request for a whole file."""
    position = start
    while end is None or position <= end:
        last = position + _UPSTREAM_CHUNK_BYTES - 1
        if end is not None:
            last = min(last, end)
        response = _get(stream, position, last)
        try:
            if response.status_code not in (200, 206):
                if response.status_code != 416:
                    logger.warning("A track stopped with %s at byte %s", response.status_code, position)
                return
            received = 0
            for chunk in response.iter_content(_READ_BYTES):
                received += len(chunk)
                yield chunk
            position += received
            # A short answer is the end of the file.
            if received < last - (position - received) + 1 or response.status_code == 200:
                return
        finally:
            response.close()


def _first_bytes(stream: MediaStream, count: int) -> bytes:
    data = bytearray()
    for chunk in _bytes_of(stream, 0, count - 1):
        data += chunk
    return bytes(data)


def _pick_track(name: str):
    """What picks the track an ``.mp4`` name stands for out of the episode's tracks."""
    match = _TRACK_NAME.match(name)
    if match is None or match.group(2) != "mp4":
        raise HTTPException(status_code=404, detail="No such track")
    if match.group(1):
        height = int(match.group(1))
        return lambda tracks: _video_track(tracks, height)
    return lambda tracks: tracks.audio


def track_redirect_response(source: Source, episode: EpisodeRef, name: str, *, head_only: bool) -> Response:
    """A redirect to one of the episode's tracks on the Site, with a link that still lasts a while,
    for a feed that lets the app fetch its Site's video itself. The app sends its range along."""
    track = _pick_track(name)(episode_tracks(source, episode))
    headers = {**_NO_CACHE_HEADERS, "Location": track.url}
    return Response(status_code=302, headers=headers) if head_only else RedirectResponse(track.url, status_code=302, headers=_NO_CACHE_HEADERS)


def track_part_response(
        source: Source, episode: EpisodeRef, name: str, *, range_header: str | None, head_only: bool,
) -> Response:
    """Bytes of one of the episode's tracks, passed on with the range the player asked for."""
    pick = _pick_track(name)
    track = pick(episode_tracks(source, episode))
    wanted = _RANGE.match((range_header or "").strip())
    start = int(wanted.group(1)) if wanted else 0
    end = int(wanted.group(2)) if wanted and wanted.group(2) else None
    if end is None and track.size_bytes:
        end = track.size_bytes - 1
    # One byte first, for the size and to tell whether the link still works.
    probe = _get(track, start, start)
    if probe.status_code == 403:
        # The link expired early: look the tracks up once more.
        probe.close()
        track = pick(episode_tracks(source, episode, fresh=True))
        probe = _get(track, start, start)
    status = probe.status_code
    total = probe.headers.get("Content-Range", "").rpartition("/")[2]
    probe.close()
    if status == 416:
        raise HTTPException(status_code=416, detail="Range not satisfiable")
    if status not in (200, 206):
        raise HTTPException(status_code=502, detail=f"{source.name} stream is currently unavailable")
    size = int(total) if total.isdigit() else track.size_bytes
    if size is not None:
        end = size - 1 if end is None else min(end, size - 1)
    headers = {**_NO_CACHE_HEADERS, "Accept-Ranges": "bytes", "Content-Type": "audio/mp4" if name.startswith("audio") else "video/mp4"}
    if end is not None:
        headers["Content-Length"] = str(end - start + 1)
    if wanted and end is not None and size is not None:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    status_code = 206 if wanted else 200
    if head_only:
        return Response(status_code=status_code, headers=headers)
    return StreamingResponse(_bytes_of(track, start, end), status_code=status_code, headers=headers)


# --- HLS -------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SegmentIndex:
    init_size: int
    """The bytes of ``ftyp`` and ``moov`` at the start of the file, which every fragment needs."""
    fragments: tuple[tuple[int, int, float], ...]
    """Offset, size and seconds of every fragment."""


_indexes: dict[str, tuple[float, SegmentIndex]] = {}


def _boxes(data: bytes) -> Iterator[tuple[int, int, bytes, int]]:
    """Offset, size, type and header size of every top-level MP4 box that starts within ``data``."""
    position = 0
    while position + 8 <= len(data):
        size = int.from_bytes(data[position:position + 4], "big")
        kind = data[position + 4:position + 8]
        header = 8
        if size == 1:
            if position + 16 > len(data):
                return
            size = int.from_bytes(data[position + 8:position + 16], "big")
            header = 16
        if size < header:
            return
        yield position, size, kind, header
        position += size


def parse_segment_index(data: bytes) -> SegmentIndex | None:
    """The segment index of a fragmented MP4 file from its first bytes; None while ``data`` ends
    before the ``sidx`` box does."""
    init_size = None
    for position, size, kind, header in _boxes(data):
        if kind == b"moov":
            init_size = position + size
        elif kind == b"sidx":
            if position + size > len(data):
                return None
            if init_size is None:
                raise HTTPException(status_code=502, detail="The video track has no moov box before its index")
            body = data[position + header:position + size]
            timescale = int.from_bytes(body[8:12], "big") or 1
            if body[0] == 0:
                first_offset, rest = int.from_bytes(body[16:20], "big"), 20
            else:
                first_offset, rest = int.from_bytes(body[20:28], "big"), 28
            count = int.from_bytes(body[rest + 2:rest + 4], "big")
            offset = position + size + first_offset
            fragments = []
            for index in range(count):
                entry = body[rest + 4 + 12 * index:rest + 16 + 12 * index]
                fragment_size = int.from_bytes(entry[0:4], "big") & 0x7FFFFFFF
                fragments.append((offset, fragment_size, int.from_bytes(entry[4:8], "big") / timescale))
                offset += fragment_size
            return SegmentIndex(init_size, tuple(fragments))
        elif kind in (b"moof", b"mdat"):
            raise HTTPException(status_code=502, detail="The video track has no segment index")
    return None


def _segment_index(track: MediaStream) -> SegmentIndex:
    with _lock_for(f"index:{track.url}"):
        kept = _indexes.get(track.url)
        if kept is not None and kept[0] > time.time():
            return kept[1]
        count = _INDEX_FIRST_BYTES
        while count <= _INDEX_MOST_BYTES:
            data = _first_bytes(track, count)
            index = parse_segment_index(data)
            if index is not None:
                until = (track.expires_at or time.time() + _UNKNOWN_EXPIRY_SECONDS)
                now = time.time()
                for other in [other for other, value in _indexes.items() if value[0] <= now]:
                    _indexes.pop(other, None)
                _indexes[track.url] = (until, index)
                return index
            if len(data) < count:
                break
            count *= 4
    raise HTTPException(status_code=502, detail="The video track's segment index could not be read")


def media_playlist(uri: str, index: SegmentIndex) -> str:
    """An HLS playlist of every fragment of one track, as byte ranges of the file at ``uri``."""
    longest = max((seconds for *_, seconds in index.fragments), default=1)
    lines = [
        "#EXTM3U", "#EXT-X-VERSION:7", f"#EXT-X-TARGETDURATION:{math.ceil(longest)}",
        "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-INDEPENDENT-SEGMENTS",
        f'#EXT-X-MAP:URI="{uri}",BYTERANGE="{index.init_size}@0"',
    ]
    for offset, size, seconds in index.fragments:
        lines += [f"#EXTINF:{seconds:.3f},", f"#EXT-X-BYTERANGE:{size}@{offset}", uri]
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def master_playlist(videos: list[MediaStream], audio: MediaStream) -> str:
    """An HLS playlist of a variant per resolution, from the highest down, that share one audio track."""
    lines = [
        "#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-INDEPENDENT-SEGMENTS",
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,URI="tracks/audio.m3u8"',
    ]
    for video in videos:
        bandwidth = (video.bitrate or 0) + (audio.bitrate or 0) or 1
        attributes = [f"BANDWIDTH={bandwidth}"]
        if video.codecs and audio.codecs:
            attributes.append(f'CODECS="{video.codecs},{audio.codecs}"')
        if video.width and video.height:
            attributes.append(f"RESOLUTION={video.width}x{video.height}")
        attributes.append('AUDIO="audio"')
        lines += [f"#EXT-X-STREAM-INF:{','.join(attributes)}", f"tracks/video-{video.height}.m3u8"]
    return "\n".join(lines) + "\n"


def _playlist_response(text: str, *, head_only: bool) -> Response:
    content = text.encode()
    headers = {**_NO_CACHE_HEADERS, "Content-Type": HLS_MIME_TYPE, "Content-Length": str(len(content))}
    return Response(content=b"" if head_only else content, headers=headers)


def master_playlist_response(source: Source, episode: EpisodeRef, *, height: int, head_only: bool) -> Response:
    tracks = episode_tracks(source, episode)
    videos = [video for video in tracks.video if (video.height or 0) <= height] or [tracks.video[-1]]
    return _playlist_response(master_playlist(videos, tracks.audio), head_only=head_only)


def track_playlist_response(source: Source, episode: EpisodeRef, name: str, *, head_only: bool) -> Response:
    match = _TRACK_NAME.match(name)
    if match is None or match.group(2) != "m3u8":
        raise HTTPException(status_code=404, detail="No such track")
    tracks = episode_tracks(source, episode)
    track = _video_track(tracks, int(match.group(1))) if match.group(1) else tracks.audio
    return _playlist_response(media_playlist(name.removesuffix(".m3u8") + ".mp4", _segment_index(track)), head_only=head_only)


# --- Joining MP4 files -----------------------------------------------------------------------------

_joining: set[str] = set()
_joins = threading.Semaphore(2)
_file_streamed: dict[str, float] = {}


def joined_key(episode_uuid: str, height: int) -> str:
    return f"{episode_uuid}-{height}p"


def joined_mp4(episode_uuid: str, height: int) -> Path | None:
    """The joined MP4 file of the episode at this resolution, when it is ready and no app is still
    playing the Site's MP4 file of it."""
    if time.time() - _file_streamed.get(episode_uuid, 0) < _SAME_FILE_SECONDS:
        return None
    return get_cached_mp4_path(joined_key(episode_uuid, height))


def note_file_streamed(episode_uuid: str) -> None:
    now = time.time()
    _file_streamed[episode_uuid] = now
    for other in [other for other, at in _file_streamed.items() if now - at >= _SAME_FILE_SECONDS]:
        _file_streamed.pop(other, None)


def _feed_pipe(track: MediaStream, pipe: Path, process: subprocess.Popen) -> None:
    """Write the track into the named pipe ffmpeg reads, once ffmpeg opens it."""
    descriptor = None
    while process.poll() is None:
        try:
            descriptor = os.open(pipe, os.O_WRONLY | os.O_NONBLOCK)
            break
        except OSError as exc:
            if exc.errno != errno.ENXIO:
                raise
            time.sleep(0.2)
    if descriptor is None:
        return
    os.set_blocking(descriptor, True)
    try:
        with os.fdopen(descriptor, "wb") as out:
            for chunk in _bytes_of(track, 0, None):
                out.write(chunk)
    except OSError:
        pass  # ffmpeg stopped reading.


def _join(video: MediaStream, audio: MediaStream, target: Path) -> None:
    """Join the tracks into an MP4 file with its index at the front, without re-encoding.

    ffmpeg reads both from named pipes that VODLoft fills 10 MB at a time, as the Site limits a single
    request for a whole file.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".join-") as working:
        pipes = [Path(working) / "video", Path(working) / "audio"]
        for pipe in pipes:
            os.mkfifo(pipe)
        temporary = Path(working) / "joined.mp4"
        command = [
            str(get_settings().download_settings.ffmpeg_path), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(pipes[0]), "-i", str(pipes[1]), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
            "-movflags", "+faststart", "-f", "mp4", str(temporary),
        ]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
        feeders = [
            threading.Thread(target=_feed_pipe, args=(track, pipe, process), daemon=True)
            for track, pipe in zip((video, audio), pipes)
        ]
        for feeder in feeders:
            feeder.start()
        try:
            _, errors = process.communicate(timeout=_JOIN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            _, errors = process.communicate()
        if process.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError(f"ffmpeg stopped with {process.returncode}: {(errors or '')[-2000:]}")
        os.replace(temporary, target)


def join_in_background(source: Source, episode: EpisodeRef, height: int) -> None:
    """Start joining the episode's MP4 at this resolution, unless it is ready or being joined."""
    key = joined_key(episode.uuid, height)
    with _guard:
        if key in _joining or get_cached_mp4_path(key) is not None:
            return
        _joining.add(key)

    def run() -> None:
        try:
            with _joins:
                tracks = episode_tracks(source, episode)
                started = time.time()
                _join(_video_track(tracks, height), tracks.audio, mp4_cache_path(key))
                logger.info("Joined the %sp MP4 of %s in %.0f s", height, episode.url, time.time() - started)
        except Exception as exc:
            logger.warning("Could not join the %sp MP4 of %s: %s", height, episode.url, exc)
        finally:
            with _guard:
                _joining.discard(key)

    threading.Thread(target=run, name="rss-join-mp4", daemon=True).start()


def joined_mp4_response(path: Path, *, filename: str) -> FileResponse:
    try:
        path.touch()
    except OSError:
        pass
    return FileResponse(
        path, filename=filename, content_disposition_type="inline", media_type="video/mp4", headers=_NO_CACHE_HEADERS,
    )
