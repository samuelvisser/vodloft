"""EXPERIMENT: several ways of streaming YouTube video to podcast apps, side by side.

This module is for testing only and is not meant to be merged as it is. It adds a second feed next to
a stream profile's own feed, ``/feeds/rss/{token}/experiments/feed.xml``, that lists the newest episodes
once for every method below, so each method can be tried in a real podcast app. Every method plays
an episode that is not downloaded; none of them looks at downloads.

The first round showed that YouTube's 360p MP4 (format 18) plays both straight from YouTube and through
VODLoft. YouTube only has higher resolutions as separate video and audio, so the other methods join
1080p H.264 video with M4A audio in different ways.

  A  redirect          302 to format 18.
  B  proxy             VODLoft passes format 18 on in 10 MB ranges (what PR #158 does).
  C  download-first    yt-dlp downloads and joins 1080p into one MP4 first, then VODLoft serves that file
                       with ranges. The first play waits until it is ready.
  D  prepared          Like C, but the file is made as soon as the feed is fetched; until it is ready,
                       the episode plays as A.
  E  hls-parts-direct  An HLS playlist that VODLoft writes from the index in YouTube's own video and audio
                       files, with every part fetched straight from YouTube. Nothing is joined or stored.
  F  hls-parts-proxy   Like E, with every part passed on through VODLoft.
  G  hls-live          ffmpeg joins video and audio into HLS parts on disk; the playlist is served while
                       it is still being made.
  H  hls-file          Like G, but the playlist is only served once every part is made.

The HLS enclosures say video/mp4, because podcast apps leave out episodes whose enclosure is HLS. Their
addresses end in .m3u8, from which players can still tell it is HLS.

``/feeds/rss/{token}/experiments/{episode}/diagnose`` shows what YouTube offers for an episode.
"""
from __future__ import annotations

import errno
import hashlib
import logging
import math
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from datetime import timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

import requests
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse

from backend.app import db_session
from backend.db.models import Episode
from backend.services.collection_cookies import uses_cookies
from backend.utils.feed_urls import request_base_url
from config import get_settings
from sources import ytdlp_runner

from .service import get_rss_stream_profile_by_token


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/feeds", tags=["Feeds"])

_NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
_UPSTREAM_CHUNK = 10 * 1024 * 1024
_READ = 64 * 1024
_TIMEOUT = 30
_KEEP_SECONDS = 60 * 60
_FILES_KEPT_SECONDS = 24 * 60 * 60
_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
_HLS_TYPE = "application/vnd.apple.mpegurl"
_HEIGHT = 1080

# method: (label, enclosure file name)
METHODS: dict[str, tuple[str, str]] = {
    "redirect": ("A 360p from YouTube", "video.mp4"),
    "proxy": ("B 360p through VODLoft", "video.mp4"),
    "download-first": ("C 1080p MP4 made first", "video.mp4"),
    "prepared": ("D 1080p MP4 made ahead, 360p until then", "video.mp4"),
    "hls-parts-direct": ("E 1080p HLS from YouTube", "video.m3u8"),
    "hls-parts-proxy": ("F 1080p HLS through VODLoft", "video.m3u8"),
    "hls-live": ("G 1080p HLS made while playing", "video.m3u8"),
    "hls-file": ("H 1080p HLS made first", "video.m3u8"),
}


# --- Looking episodes up --------------------------------------------------------------------------

_infos: dict[str, tuple[float, dict]] = {}
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def _info(url: str, *, cookies: bool) -> dict:
    """yt-dlp's info for the video, kept for an hour."""
    with _lock(f"info:{url}"):
        kept = _infos.get(url)
        if kept is not None and kept[0] > time.time():
            return kept[1]
        try:
            info = ytdlp_runner.run_json("--no-playlist", url, cookies=cookies)
        except ytdlp_runner.YtDlpError as exc:
            raise HTTPException(status_code=502, detail=f"yt-dlp: {exc}") from exc
        _infos[url] = (time.time() + _KEEP_SECONDS, info)
        return info


def _formats(info: dict) -> list[dict]:
    return [fmt for fmt in info.get("formats") or [] if fmt.get("url")]


def _has(fmt: dict, kind: str) -> bool:
    return (fmt.get(kind) or "none") != "none"


def _direct(fmt: dict) -> bool:
    return str(fmt.get("protocol", "")).startswith("http")


def _format_18(info: dict) -> dict | None:
    return next((fmt for fmt in _formats(info) if fmt.get("format_id") == "18"), None)


def _video_1080(info: dict) -> dict | None:
    """The best H.264 video without sound up to 1080p."""
    candidates = [
        fmt for fmt in _formats(info)
        if _has(fmt, "vcodec") and not _has(fmt, "acodec") and str(fmt.get("vcodec", "")).startswith("avc1")
        and fmt.get("ext") == "mp4" and _direct(fmt) and (fmt.get("height") or 0) <= _HEIGHT
    ]
    return max(candidates, key=lambda fmt: (fmt.get("height") or 0, fmt.get("tbr") or 0), default=None)


def _audio_m4a(info: dict) -> dict | None:
    """The M4A audio in the video's original language (dubbed videos list one per language)."""
    candidates = [
        fmt for fmt in _formats(info)
        if not _has(fmt, "vcodec") and _has(fmt, "acodec") and fmt.get("ext") == "m4a" and _direct(fmt)
        and not str(fmt.get("format_id")).endswith("-drc")
    ]
    return max(
        candidates,
        key=lambda fmt: (fmt.get("language_preference") or 0, str(fmt.get("format_id")).startswith("140"), fmt.get("abr") or 0),
        default=None,
    )


def _video_and_audio(info: dict) -> tuple[dict, dict]:
    video, audio = _video_1080(info), _audio_m4a(info)
    if video is None or audio is None:
        raise HTTPException(status_code=404, detail="No H.264 video or M4A audio; see /diagnose")
    return video, audio


def _required_18(info: dict) -> dict:
    fmt = _format_18(info)
    if fmt is None:
        raise HTTPException(status_code=404, detail="No format 18; see /diagnose")
    return fmt


# --- Passing bytes on ------------------------------------------------------------------------------

def _headers_of(fmt: dict) -> dict[str, str]:
    return {str(name): str(value) for name, value in (fmt.get("http_headers") or {}).items()}


def _media_headers(media_type: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    return {**_NO_CACHE, "Accept-Ranges": "bytes", "Content-Type": media_type, **(extra or {})}


def _upstream_chunks(fmt: dict, start: int, end: int | None) -> Iterator[bytes]:
    """The format's bytes from ``start`` to ``end``, asked of YouTube 10 MB at a time."""
    position = start
    while end is None or position <= end:
        last = position + _UPSTREAM_CHUNK - 1
        if end is not None:
            last = min(last, end)
        upstream = requests.get(
            fmt["url"], headers={**_headers_of(fmt), "Range": f"bytes={position}-{last}"}, stream=True, timeout=_TIMEOUT,
        )
        try:
            if upstream.status_code == 416:
                return
            if upstream.status_code not in (200, 206):
                logger.warning("YouTube experiment: upstream answered %s", upstream.status_code)
                return
            received = 0
            for chunk in upstream.iter_content(_READ):
                received += len(chunk)
                yield chunk
            position += received
            if received == 0 or upstream.status_code == 200:
                return
        finally:
            upstream.close()


def _chunked(fmt: dict, *, range_header: str | None, head_only: bool, media_type: str = "video/mp4") -> Response:
    """PR #158's way: YouTube in 10 MB ranges, whatever the player asked for."""
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    start, end = 0, None
    if range_header and range_header.startswith("bytes="):
        first, _, last = range_header.removeprefix("bytes=").partition("-")
        start = int(first or 0)
        end = int(last) if last else None
    if size:
        end = min(end, size - 1) if end is not None else size - 1
    extra = {}
    if end is not None:
        extra["Content-Length"] = str(end - start + 1)
    if range_header and size:
        extra["Content-Range"] = f"bytes {start}-{end}/{size}"
    status = 206 if range_header else 200
    headers = _media_headers(media_type, extra)
    if head_only:
        return Response(status_code=status, headers=headers)
    return StreamingResponse(_upstream_chunks(fmt, start, end), status_code=status, headers=headers)


# --- Files on disk ---------------------------------------------------------------------------------

def _root() -> Path:
    root = Path(get_settings().download_settings.rss_cache_root) / "youtube-experiment"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _key(episode_uuid: str) -> str:
    return hashlib.sha256(episode_uuid.encode()).hexdigest()[:24]


def _clean_up() -> None:
    """Remove what earlier tries made more than a day ago."""
    cutoff = time.time() - _FILES_KEPT_SECONDS
    for entry in _root().iterdir():
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
        except OSError:
            pass


# --- C and D: one MP4, made first ------------------------------------------------------------------

_building: set[str] = set()
_builds = threading.Semaphore(2)


def _mp4_path(episode_uuid: str) -> Path:
    return _root() / f"{_key(episode_uuid)}.mp4"


def _build_mp4(episode_uuid: str, url: str, cookies: bool) -> Path:
    """yt-dlp downloads 1080p H.264 and M4A audio and joins them, with the index at the front."""
    path = _mp4_path(episode_uuid)
    with _lock(f"mp4:{path}"):
        if path.is_file():
            return path
        _clean_up()
        with _builds:
            started = time.time()
            settings = get_settings().download_settings
            working = path.with_name(f"{path.stem}.building")
            command = [
                *ytdlp_runner.command(cookies=cookies), "--no-playlist", "--no-progress",
                "-f", f"bv*[height<={_HEIGHT}][vcodec^=avc1][ext=mp4]+ba[ext=m4a]/b[ext=mp4]",
                "--merge-output-format", "mp4", "--ffmpeg-location", str(settings.ffmpeg_path),
                "--postprocessor-args", "Merger+ffmpeg_o:-movflags +faststart",
                "-o", f"{working}.%(ext)s", url,
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=60 * 60)
            made = working.with_suffix(".building.mp4")
            if result.returncode != 0 or not made.is_file():
                for leftover in path.parent.glob(f"{path.stem}.building*"):
                    leftover.unlink(missing_ok=True)
                raise HTTPException(status_code=502, detail=f"yt-dlp failed: {result.stderr[-800:]}")
            made.replace(path)
            logger.info("YouTube experiment: made %s in %.0f s", path.name, time.time() - started)
            return path


def _prepare_in_background(episode_uuid: str, url: str, cookies: bool) -> None:
    with _guard:
        if episode_uuid in _building or _mp4_path(episode_uuid).is_file():
            return
        _building.add(episode_uuid)

    def run() -> None:
        try:
            _build_mp4(episode_uuid, url, cookies)
        except Exception:
            logger.exception("YouTube experiment: preparing %s failed", url)
        finally:
            with _guard:
                _building.discard(episode_uuid)

    threading.Thread(target=run, name="youtube-experiment-prepare", daemon=True).start()


def _serve_file(path: Path, media_type: str) -> FileResponse:
    return FileResponse(path, media_type=media_type, headers=_NO_CACHE, content_disposition_type="inline")


# --- E and F: HLS from YouTube's own files ---------------------------------------------------------
#
# YouTube's video-only and audio-only MP4 files are fragmented: ``ftyp`` and ``moov`` first, then a
# ``sidx`` box that lists every fragment's size and duration. That is all an HLS playlist needs: the
# first boxes as its EXT-X-MAP, and every fragment as a byte range of the same file.

_indexes: dict[tuple[str, str], tuple[float, tuple[int, list[tuple[int, int, float]]]]] = {}


def _boxes(data: bytes) -> Iterator[tuple[int, int, bytes, int]]:
    """(offset, size, type, header size) of every top-level box that starts within ``data``."""
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


def parse_index(data: bytes) -> tuple[int, list[tuple[int, int, float]]] | None:
    """The size of the file's init part and (offset, size, seconds) of every fragment, from its first
    bytes; None when ``data`` does not reach the end of the ``sidx`` box yet."""
    init_end = None
    for position, size, kind, header in _boxes(data):
        if kind == b"moov":
            init_end = position + size
        elif kind == b"sidx":
            if position + size > len(data):
                return None
            body = data[position + header:position + size]
            timescale = int.from_bytes(body[8:12], "big")
            if body[0] == 0:
                first_offset, rest = int.from_bytes(body[16:20], "big"), 20
            else:
                first_offset, rest = int.from_bytes(body[20:28], "big"), 28
            count = int.from_bytes(body[rest + 2:rest + 4], "big")
            offset = position + size + first_offset
            fragments = []
            for index in range(count):
                entry = body[rest + 4 + 12 * index:rest + 16 + 12 * index]
                referenced = int.from_bytes(entry[0:4], "big") & 0x7FFFFFFF
                fragments.append((offset, referenced, int.from_bytes(entry[4:8], "big") / timescale))
                offset += referenced
            if init_end is None:
                raise HTTPException(status_code=502, detail="The file has a segment index but no moov box")
            return init_end, fragments
        elif kind in (b"moof", b"mdat"):
            raise HTTPException(status_code=502, detail="The file has no segment index")
    return None


def _first_bytes(fmt: dict, count: int) -> bytes:
    upstream = requests.get(
        fmt["url"], headers={**_headers_of(fmt), "Range": f"bytes=0-{count - 1}"}, stream=True, timeout=_TIMEOUT,
    )
    try:
        if upstream.status_code not in (200, 206):
            raise HTTPException(status_code=502, detail=f"YouTube answered {upstream.status_code}")
        data = bytearray()
        for chunk in upstream.iter_content(_READ):
            data += chunk
            if len(data) >= count:
                break
        return bytes(data[:count])
    finally:
        upstream.close()


def _index(url: str, fmt: dict) -> tuple[int, list[tuple[int, int, float]]]:
    key = (url, str(fmt.get("format_id")))
    with _lock(f"index:{key}"):
        kept = _indexes.get(key)
        if kept is not None and kept[0] > time.time():
            return kept[1]
        count = 256 * 1024
        while count <= 16 * 1024 * 1024:
            parsed = parse_index(_first_bytes(fmt, count))
            if parsed is not None:
                _indexes[key] = (time.time() + _KEEP_SECONDS, parsed)
                return parsed
            count *= 4
        raise HTTPException(status_code=502, detail="The segment index did not end in the first 16 MB")


def media_playlist(uri: str, init_size: int, fragments: list[tuple[int, int, float]]) -> str:
    lines = [
        "#EXTM3U", "#EXT-X-VERSION:7",
        f"#EXT-X-TARGETDURATION:{math.ceil(max((seconds for *_, seconds in fragments), default=1))}",
        "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-INDEPENDENT-SEGMENTS",
        f'#EXT-X-MAP:URI="{uri}",BYTERANGE="{init_size}@0"',
    ]
    for offset, size, seconds in fragments:
        lines += [f"#EXTINF:{seconds:.3f},", f"#EXT-X-BYTERANGE:{size}@{offset}", uri]
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def master_playlist(video: dict, audio: dict) -> str:
    bandwidth = int(((video.get("tbr") or 5000) + (audio.get("tbr") or audio.get("abr") or 128)) * 1000)
    resolution = f",RESOLUTION={video['width']}x{video['height']}" if video.get("width") and video.get("height") else ""
    return "\n".join([
        "#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-INDEPENDENT-SEGMENTS",
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,URI="audio-track.m3u8"',
        f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},CODECS="{video.get("vcodec")},{audio.get("acodec")}"{resolution},AUDIO="audio"',
        "video-track.m3u8",
    ]) + "\n"


def _playlist_response(text: str, *, head_only: bool) -> Response:
    content = text.encode()
    headers = {**_NO_CACHE, "Content-Type": _HLS_TYPE, "Content-Length": str(len(content))}
    return Response(content=b"" if head_only else content, headers=headers)


def _hls_parts(method: str, filename: str, url: str, cookies: bool, *, head_only: bool) -> Response:
    info = _info(url, cookies=cookies)
    video, audio = _video_and_audio(info)
    if filename == "video.m3u8":
        return _playlist_response(master_playlist(video, audio), head_only=head_only)
    track = {"video-track.m3u8": video, "audio-track.m3u8": audio}.get(filename)
    if track is None:
        raise HTTPException(status_code=404, detail="No such playlist")
    init_size, fragments = _index(url, track)
    uri = track["url"] if method == "hls-parts-direct" else f"part/{track['format_id']}"
    return _playlist_response(media_playlist(uri, init_size, fragments), head_only=head_only)


# --- G and H: HLS made by ffmpeg -------------------------------------------------------------------

_hls_processes: dict[str, subprocess.Popen] = {}
_HLS_PART = re.compile(r"^(init\.mp4|part\d{5}\.m4s)$")


def _feed_pipe(fmt: dict, pipe: Path, process: subprocess.Popen) -> None:
    """Write the format into the named pipe that ffmpeg reads, once ffmpeg opens it."""
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
            for chunk in _upstream_chunks(fmt, 0, None):
                out.write(chunk)
    except (BrokenPipeError, OSError):
        pass


def _start_hls(episode_uuid: str, url: str, cookies: bool) -> Path:
    directory = _root() / f"hls-{_key(episode_uuid)}"
    with _lock(f"hls:{directory}"):
        process = _hls_processes.get(str(directory))
        if (directory / "done").is_file() or (process is not None and process.poll() is None):
            return directory
        _clean_up()
        video, audio = _video_and_audio(_info(url, cookies=cookies))
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
        pipes = [directory / "video.pipe", directory / "audio.pipe"]
        for pipe in pipes:
            os.mkfifo(pipe)
        command = [
            str(get_settings().download_settings.ffmpeg_path), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(pipes[0]), "-i", str(pipes[1]), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
            "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "event", "-hls_segment_type", "fmp4",
            "-hls_flags", "temp_file+independent_segments",
            "-hls_fmp4_init_filename", "init.mp4", "-hls_segment_filename", str(directory / "part%05d.m4s"),
            str(directory / "index.m3u8"),
        ]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        _hls_processes[str(directory)] = process
        for fmt, pipe in zip((video, audio), pipes):
            threading.Thread(target=_feed_pipe, args=(fmt, pipe, process), daemon=True).start()

        def finish() -> None:
            errors = process.stderr.read()
            if process.wait() == 0:
                (directory / "done").touch()
            else:
                (directory / "error").write_text(errors[-2000:] or f"ffmpeg stopped with {process.returncode}")
            for pipe in pipes:
                pipe.unlink(missing_ok=True)

        threading.Thread(target=finish, daemon=True).start()
        return directory


def _hls_made(method: str, filename: str, episode_uuid: str, url: str, cookies: bool, *, head_only: bool) -> Response:
    directory = _start_hls(episode_uuid, url, cookies)
    if filename != "video.m3u8":
        if not _HLS_PART.match(filename) or not (directory / filename).is_file():
            raise HTTPException(status_code=404, detail="No such part")
        return _serve_file(directory / filename, "video/mp4")

    playlist = directory / "index.m3u8"
    give_up = time.time() + (90 if method == "hls-live" else 30 * 60)
    while time.time() < give_up:
        if (directory / "error").is_file():
            raise HTTPException(status_code=502, detail=f"ffmpeg failed: {(directory / 'error').read_text()}")
        done = (directory / "done").is_file()
        text = playlist.read_text() if playlist.is_file() else ""
        if done or (method == "hls-live" and text.count("#EXTINF") >= 2):
            # Start at the beginning, not at the newest part, while the playlist still grows.
            return _playlist_response(text.replace("#EXTM3U", "#EXTM3U\n#EXT-X-START:TIME-OFFSET=0", 1), head_only=head_only)
        time.sleep(1)
    raise HTTPException(status_code=504, detail="The HLS parts were not ready in time")


# --- Routes ----------------------------------------------------------------------------------------

def _episodes(s, profile, limit: int) -> list[Episode]:
    return (
        s.query(Episode)
        .filter(Episode.collection_id == profile.collection_id, Episode.publish_status.in_(("published_final", "published_preliminary")))
        .order_by(Episode.published_date.desc())
        .limit(limit)
        .all()
    )


@router.api_route("/rss/{token}/experiments/feed.xml", methods=["GET", "HEAD"])
def experiments_feed(token: str, request: Request, episodes: int = 2):
    with db_session() as s:
        profile = get_rss_stream_profile_by_token(s, token)
        collection = profile.collection
        cookies = uses_cookies(collection)
        items = [
            (episode.slug, episode.uuid, episode.sharing_url, episode.title, episode.published_date, episode.duration,
             episode.description)
            for episode in _episodes(s, profile, max(1, min(episodes, 10)))
        ]
        title = collection.title

    if request.method == "GET":
        for _slug, uuid, sharing_url, *_rest in items:
            _prepare_in_background(uuid, sharing_url, cookies)

    base = f"{request_base_url(request)}/feeds/rss/{token}/experiments"
    register_namespace("itunes", _ITUNES)
    rss = Element("rss", {"version": "2.0"})
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = f"{title} (YouTube experiments)"
    SubElement(channel, "link").text = base
    SubElement(channel, "description").text = "Every episode once per streaming method, to see which ones play."
    SubElement(channel, "{%s}type" % _ITUNES).text = "episodic"
    for slug, _uuid, _url, episode_title, published, duration, description in items:
        for index, (method, (label, filename)) in enumerate(METHODS.items()):
            item = SubElement(channel, "item")
            SubElement(item, "title").text = f"[{label}] {episode_title}"
            SubElement(item, "guid", {"isPermaLink": "false"}).text = f"{slug}-{method}-2"
            SubElement(item, "description").text = f"Method {method}. {description or ''}"
            if published is not None:
                # A second apart, so apps keep the methods in order.
                published_at = published if published.tzinfo else published.replace(tzinfo=timezone.utc)
                SubElement(item, "pubDate").text = format_datetime(published_at - timedelta(seconds=index))
            if duration:
                SubElement(item, "{%s}duration" % _ITUNES).text = str(int(duration))
            SubElement(item, "{%s}episode" % _ITUNES).text = str(index + 1)
            SubElement(item, "enclosure", {"url": f"{base}/{slug}/{method}/{filename}", "type": "video/mp4", "length": "0"})
    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(rss)
    return Response(
        content=b"" if request.method == "HEAD" else xml, media_type="application/rss+xml; charset=utf-8", headers=_NO_CACHE,
    )


def _episode(token: str, episode_slug: str) -> tuple[str, str, bool]:
    with db_session() as s:
        profile = get_rss_stream_profile_by_token(s, token)
        episode = s.query(Episode).filter_by(slug=episode_slug, collection_id=profile.collection_id).one_or_none()
        if episode is None:
            raise HTTPException(status_code=404, detail="Episode not found")
        return episode.sharing_url, episode.uuid, uses_cookies(episode.collection)


@router.get("/rss/{token}/experiments/{episode_slug}/diagnose")
def experiments_diagnose(token: str, episode_slug: str):
    url, uuid, cookies = _episode(token, episode_slug)
    started = time.time()
    info = _info(url, cookies=cookies)
    report = {"url": url, "cookies": cookies, "seconds": round(time.time() - started, 1)}
    video, audio = _video_1080(info), _audio_m4a(info)
    report.update({
        "format_18": bool(_format_18(info)),
        "video": (video or {}).get("format_id"), "audio": (audio or {}).get("format_id"),
        "mp4_ready": _mp4_path(uuid).is_file(), "mp4_preparing": uuid in _building,
    })
    for name, fmt in (("video_index", video), ("audio_index", audio)):
        if fmt is None:
            continue
        try:
            init_size, fragments = _index(url, fmt)
            report[name] = {"init_bytes": init_size, "parts": len(fragments),
                            "seconds": round(sum(seconds for *_, seconds in fragments), 1)}
        except HTTPException as exc:
            report[name] = {"error": exc.detail}
    hls = _root() / f"hls-{_key(uuid)}"
    if (hls / "error").is_file():
        report["hls_error"] = (hls / "error").read_text()
    report["formats"] = [
        {
            "id": fmt.get("format_id"), "ext": fmt.get("ext"), "protocol": fmt.get("protocol"),
            "vcodec": fmt.get("vcodec"), "acodec": fmt.get("acodec"), "height": fmt.get("height"),
            "language_preference": fmt.get("language_preference"),
            "size": fmt.get("filesize") or fmt.get("filesize_approx"), "url_host": urlsplit(fmt["url"]).hostname,
        }
        for fmt in _formats(info)
    ]
    return JSONResponse(report, headers=_NO_CACHE)


@router.get("/rss/{token}/experiments/{episode_slug}/check")
def experiments_check(token: str, episode_slug: str, request: Request):
    """Ask the quick methods for their first bytes from VODLoft itself, and say what each one answered."""
    base = f"{request_base_url(request)}/feeds/rss/{token}/experiments/{episode_slug}"
    report = {}
    for method, (_label, filename) in METHODS.items():
        if method in ("download-first", "hls-file"):
            report[method] = "skipped: makes everything first"
            continue
        names = [filename] + (["video-track.m3u8", "audio-track.m3u8"] if method.startswith("hls-parts") else [])
        for name in names:
            started = time.time()
            try:
                response = requests.get(
                    f"{base}/{method}/{name}", headers={"Range": "bytes=0-1023"}, stream=True, timeout=120,
                    allow_redirects=False,
                )
                first = next(response.iter_content(1024), b"")
                report[f"{method}/{name}"] = {
                    "status": response.status_code, "seconds": round(time.time() - started, 1),
                    "content_type": response.headers.get("Content-Type"), "range": response.headers.get("Content-Range"),
                    "location": (response.headers.get("Location") or "")[:80] or None,
                    "start": first[:300].decode(errors="replace"),
                }
                response.close()
            except Exception as exc:
                report[f"{method}/{name}"] = {"error": str(exc)}
    return JSONResponse(report, headers=_NO_CACHE)


@router.api_route("/rss/{token}/experiments/{episode_slug}/{method}/part/{format_id}", methods=["GET", "HEAD"])
def experiments_part(token: str, episode_slug: str, method: str, format_id: str, request: Request):
    """Part of YouTube's video or audio file, passed on (method F)."""
    url, _uuid, cookies = _episode(token, episode_slug)
    fmt = next((fmt for fmt in _formats(_info(url, cookies=cookies)) if str(fmt.get("format_id")) == format_id), None)
    if fmt is None:
        raise HTTPException(status_code=404, detail="No such format")
    media_type = "video/mp4" if _has(fmt, "vcodec") else "audio/mp4"
    return _chunked(fmt, range_header=request.headers.get("range"), head_only=request.method == "HEAD", media_type=media_type)


@router.api_route("/rss/{token}/experiments/{episode_slug}/{method}/{filename}", methods=["GET", "HEAD"])
def experiments_media(token: str, episode_slug: str, method: str, filename: str, request: Request):
    if method not in METHODS:
        raise HTTPException(status_code=404, detail="Unknown method")
    url, uuid, cookies = _episode(token, episode_slug)
    head_only = request.method == "HEAD"
    range_header = request.headers.get("range")
    logger.info("YouTube experiment %s for %s: %s %s %s", method, episode_slug, request.method, filename, range_header)

    if method == "redirect":
        return RedirectResponse(_required_18(_info(url, cookies=cookies))["url"], status_code=302, headers=_NO_CACHE)
    if method == "proxy":
        return _chunked(_required_18(_info(url, cookies=cookies)), range_header=range_header, head_only=head_only)
    if method == "download-first":
        return _serve_file(_build_mp4(uuid, url, cookies), "video/mp4")
    if method == "prepared":
        if _mp4_path(uuid).is_file():
            return _serve_file(_mp4_path(uuid), "video/mp4")
        _prepare_in_background(uuid, url, cookies)
        return RedirectResponse(_required_18(_info(url, cookies=cookies))["url"], status_code=302, headers=_NO_CACHE)
    if method.startswith("hls-parts"):
        return _hls_parts(method, filename, url, cookies, head_only=head_only)
    return _hls_made(method, filename, uuid, url, cookies, head_only=head_only)
