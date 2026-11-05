"""EXPERIMENT: ways of streaming YouTube live streams to podcast apps, side by side.

This module is for testing only and is not meant to be merged as it is. It adds a feed next to a
stream profile's own feed that lists live YouTube videos once for every method below:

    /feeds/rss/{token}/experiments/live/feed.xml?v=<video id>,<video id>

Without ``v`` it lists the profile's collection's episodes that are live now. Any live YouTube video
works, such as a 24/7 news channel's.

Video, as HLS (the enclosure says video/mp4, as apps leave HLS episodes out):
  A  redirect      302 to YouTube's own master playlist.
  B  direct        VODLoft writes the master playlist; each variant comes from VODLoft, which fetches
                   YouTube's current variant playlist and points every segment straight at YouTube.
  C  proxy         Like B, with every segment passed on through VODLoft.

Audio, from YouTube's separate live audio, or from the lowest video variant when that has sound:
  D  audio-hls     ffmpeg writes the audio as a live audio-only HLS playlist.
  E  audio-aac     ffmpeg sends the audio as one endless AAC stream, without length or seeking.

  F  feed-shape    The shape a real feed would have: E as the enclosure, and B as a Podcasting 2.0
                   alternate enclosure of type HLS.

``/feeds/rss/{token}/experiments/live/{video id}/diagnose`` shows what each YouTube player client
offers for the video, and ``.../check`` fetches the first playlist and segment of every method.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

import requests
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse

from backend.app import db_session
from backend.db.models import Episode
from backend.services.collection_cookies import uses_cookies
from backend.types.episode_types import EpisodePublishStatus
from backend.utils.feed_urls import request_base_url
from config import get_settings
from sources import ytdlp_runner

from .service import get_rss_stream_profile_by_token


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/feeds", tags=["Feeds"])

_NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
_HLS_TYPE = "application/vnd.apple.mpegurl"
_READ = 64 * 1024
_TIMEOUT = 30
_KEEP_SECONDS = 20 * 60
_IDLE_SECONDS = 2 * 60
_MAX_HEIGHT = 1080
_CLIENTS = (None, "web", "mweb", "ios", "tv", "android_vr")
_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
_PODCAST = "https://podcastindex.org/namespace/1.0"
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
_ALLOWED_HOSTS = ("googlevideo.com", "youtube.com")

# method: (label, enclosure file name, enclosure type)
METHODS: dict[str, tuple[str, str, str]] = {
    "redirect": ("A live, redirect to YouTube", "video.m3u8", "video/mp4"),
    "direct": ("B live, segments from YouTube", "video.m3u8", "video/mp4"),
    "proxy": ("C live, segments through VODLoft", "video.m3u8", "video/mp4"),
    "audio-hls": ("D live audio as HLS", "audio.m3u8", "audio/mp4"),
    "audio-aac": ("E live audio as AAC", "audio.aac", "audio/aac"),
    "feed-shape": ("F live, audio with HLS alternate", "audio.aac", "audio/aac"),
}


# --- Looking videos up -----------------------------------------------------------------------------

_infos: dict[tuple[str, str | None], tuple[float, dict]] = {}
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def _watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _info(video_id: str, *, client: str | None = None, cookies: bool = False, fresh: bool = False) -> dict:
    key = (video_id, client)
    with _lock(f"info:{key}"):
        kept = _infos.get(key)
        if kept is not None and not fresh and kept[0] > time.time():
            return kept[1]
        args = ["--no-playlist"]
        if client:
            args += ["--extractor-args", f"youtube:player_client={client}"]
        try:
            info = ytdlp_runner.run_json(*args, _watch_url(video_id), cookies=cookies)
        except ytdlp_runner.YtDlpError as exc:
            raise HTTPException(status_code=502, detail=f"yt-dlp ({client or 'default'}): {exc}") from exc
        _infos[key] = (time.time() + _KEEP_SECONDS, info)
        return info


def live_variants(info: dict) -> list[dict]:
    """The live HLS variants with video and sound up to 1080p, from the highest down."""
    variants = [
        fmt for fmt in info.get("formats") or []
        if fmt.get("url") and "m3u8" in str(fmt.get("protocol", ""))
        and (fmt.get("vcodec") or "none") != "none" and (fmt.get("height") or 0) <= _MAX_HEIGHT
    ]
    return sorted(variants, key=lambda fmt: (fmt.get("height") or 0, fmt.get("tbr") or 0), reverse=True)


def live_audio(info: dict) -> dict | None:
    """The live HLS audio without video, in the language the video was made in. YouTube's live
    streams can list their audio apart from the video variants, which then have no sound."""
    audio = [
        fmt for fmt in info.get("formats") or []
        if fmt.get("url") and "m3u8" in str(fmt.get("protocol", ""))
        and (fmt.get("vcodec") or "none") == "none" and (fmt.get("acodec") or "none") != "none"
    ]
    return max(audio, key=lambda fmt: (fmt.get("language_preference") or 0, fmt.get("tbr") or fmt.get("abr") or 0), default=None)


def _has_sound(fmt: dict) -> bool:
    return (fmt.get("acodec") or "none") != "none"


def _audio(video_id: str, *, cookies: bool, fresh: bool = False) -> dict | None:
    """The separate live audio, when the video variants have no sound of their own."""
    variants = _variants(video_id, cookies=cookies, fresh=fresh)
    if all(_has_sound(fmt) for fmt in variants):
        return None
    return live_audio(_info(video_id, cookies=cookies, fresh=fresh))


def _variants(video_id: str, *, cookies: bool, fresh: bool = False) -> list[dict]:
    info = _info(video_id, cookies=cookies, fresh=fresh)
    if info.get("live_status") != "is_live":
        raise HTTPException(status_code=404, detail=f"The video is not live ({info.get('live_status')})")
    variants = live_variants(info)
    if not variants:
        raise HTTPException(status_code=404, detail="No live HLS variants; see /diagnose")
    return variants


def _headers_of(fmt: dict) -> dict[str, str]:
    return {str(name): str(value) for name, value in (fmt.get("http_headers") or {}).items()}


# --- Playlists -------------------------------------------------------------------------------------

def master_playlist(variants: list[dict], audio: dict | None = None) -> str:
    """One entry per variant; ``audio`` is the separate sound that variants without it share."""
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS"]
    if audio is not None:
        lines.append(
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,'
            f'URI="variant-{audio["format_id"]}.m3u8"'
        )
    for fmt in variants:
        separate = audio is not None and not _has_sound(fmt)
        bitrate = (fmt.get("tbr") or 1000) + ((audio.get("tbr") or audio.get("abr") or 128) if separate else 0)
        attributes = [f"BANDWIDTH={int(bitrate * 1000)}"]
        if fmt.get("width") and fmt.get("height"):
            attributes.append(f"RESOLUTION={fmt['width']}x{fmt['height']}")
        acodec = audio.get("acodec") if separate else fmt.get("acodec")
        if fmt.get("vcodec") and acodec and acodec != "none":
            attributes.append(f'CODECS="{fmt["vcodec"]},{acodec}"')
        if separate:
            attributes.append('AUDIO="audio"')
        lines += [f"#EXT-X-STREAM-INF:{','.join(attributes)}", f"variant-{fmt['format_id']}.m3u8"]
    return "\n".join(lines) + "\n"


def rewrite_playlist(text: str, base_url: str, proxy) -> str:
    """Every URI in the playlist made absolute, and passed through ``proxy`` when it is given."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            absolute = urljoin(base_url, stripped)
            out.append(proxy(absolute) if proxy else absolute)
        elif 'URI="' in line:
            before, _, rest = line.partition('URI="')
            uri, _, after = rest.partition('"')
            absolute = urljoin(base_url, uri)
            out.append(f'{before}URI="{proxy(absolute) if proxy else absolute}"{after}')
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def _allowed(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in _ALLOWED_HOSTS)


def _playlist_response(text: str, *, head_only: bool) -> Response:
    content = text.encode()
    headers = {**_NO_CACHE, "Content-Type": _HLS_TYPE, "Content-Length": str(len(content))}
    return Response(content=b"" if head_only else content, headers=headers)


def _variant_playlist(video_id: str, format_id: str, *, cookies: bool, proxy_base: str | None) -> str:
    """YouTube's current playlist of one variant, looked up again once when YouTube refuses its link."""
    for fresh in (False, True):
        audio = _audio(video_id, cookies=cookies, fresh=fresh)
        choices = [*_variants(video_id, cookies=cookies, fresh=fresh), *([audio] if audio else [])]
        fmt = next((fmt for fmt in choices if str(fmt.get("format_id")) == format_id), None)
        if fmt is None:
            raise HTTPException(status_code=404, detail="No such variant")
        upstream = requests.get(fmt["url"], headers=_headers_of(fmt), timeout=_TIMEOUT)
        if upstream.status_code == 200:
            proxy = (lambda url: f"{proxy_base}?u={quote(url, safe='')}") if proxy_base else None
            return rewrite_playlist(upstream.text, fmt["url"], proxy)
        logger.warning("Live experiment: YouTube answered %s for variant %s", upstream.status_code, format_id)
    raise HTTPException(status_code=502, detail=f"YouTube answered {upstream.status_code} for the variant playlist")


def _segment_response(url: str, *, range_header: str | None, head_only: bool) -> Response:
    if not _allowed(url):
        raise HTTPException(status_code=400, detail="Not a YouTube address")
    headers = {"Range": range_header} if range_header else {}
    upstream = requests.get(url, headers=headers, stream=True, timeout=_TIMEOUT)
    if upstream.status_code not in (200, 206):
        upstream.close()
        raise HTTPException(status_code=502, detail=f"YouTube answered {upstream.status_code} for a segment")
    passed = {name: upstream.headers[name] for name in ("Content-Length", "Content-Range") if name in upstream.headers}
    response_headers = {**_NO_CACHE, "Content-Type": upstream.headers.get("Content-Type", "video/mp2t"), **passed}
    if head_only:
        upstream.close()
        return Response(status_code=upstream.status_code, headers=response_headers)

    def body() -> Iterator[bytes]:
        try:
            yield from upstream.iter_content(_READ)
        finally:
            upstream.close()

    return StreamingResponse(body(), status_code=upstream.status_code, headers=response_headers)


# --- Audio by ffmpeg -------------------------------------------------------------------------------

def _ffmpeg_input(fmt: dict) -> list[str]:
    headers = _headers_of(fmt)
    command = []
    agent = headers.pop("User-Agent", None)
    if agent:
        command += ["-user_agent", agent]
    if headers:
        command += ["-headers", "".join(f"{name}: {value}\r\n" for name, value in headers.items())]
    return [*command, "-i", fmt["url"]]


def _ffmpeg() -> str:
    return str(get_settings().download_settings.ffmpeg_path)


class _AudioHls:
    def __init__(self, process: subprocess.Popen, directory: Path):
        self.process = process
        self.directory = directory
        self.used = time.time()


_audio_hls: dict[str, _AudioHls] = {}


def _root() -> Path:
    root = Path(get_settings().download_settings.rss_cache_root) / "youtube-live-experiment"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _stop_idle() -> None:
    now = time.time()
    for video_id, running in list(_audio_hls.items()):
        if now - running.used > _IDLE_SECONDS or running.process.poll() is not None:
            running.process.kill()
            running.process.wait()
            shutil.rmtree(running.directory, ignore_errors=True)
            _audio_hls.pop(video_id, None)


def _start_audio_hls(video_id: str, *, cookies: bool) -> _AudioHls:
    """ffmpeg writing the live audio as a live audio-only HLS playlist; stopped when no
    app asked for it for two minutes."""
    with _lock(f"audio:{video_id}"):
        with _guard:
            _stop_idle()
            running = _audio_hls.get(video_id)
        if running is not None:
            running.used = time.time()
            return running
        lowest = _audio(video_id, cookies=cookies) or _variants(video_id, cookies=cookies)[-1]
        directory = _root() / f"audio-{video_id}"
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
        command = [
            _ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *_ffmpeg_input(lowest),
            "-vn", "-map", "0:a:0", "-c:a", "copy", "-f", "hls", "-hls_time", "6", "-hls_list_size", "30",
            "-hls_flags", "delete_segments+temp_file+independent_segments", "-hls_segment_type", "mpegts",
            "-hls_segment_filename", str(directory / "part%06d.ts"), str(directory / "index.m3u8"),
        ]
        with open(directory / "ffmpeg.log", "wb") as log:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log)
        running = _AudioHls(process, directory)
        with _guard:
            _audio_hls[video_id] = running
        return running


def _audio_hls_response(video_id: str, filename: str, *, cookies: bool, head_only: bool) -> Response:
    running = _start_audio_hls(video_id, cookies=cookies)
    if filename == "audio.m3u8":
        playlist = running.directory / "index.m3u8"
        give_up = time.time() + 45
        while time.time() < give_up:
            text = playlist.read_text() if playlist.is_file() else ""
            if text.count("#EXTINF") >= 2:
                return _playlist_response(text, head_only=head_only)
            if running.process.poll() is not None:
                log = running.directory / "ffmpeg.log"
                detail = log.read_text(errors="replace")[-1000:] if log.is_file() else ""
                raise HTTPException(status_code=502, detail=f"ffmpeg stopped: {detail}")
            time.sleep(1)
        raise HTTPException(status_code=504, detail="The audio playlist was not ready in time")
    if not re.fullmatch(r"part\d{6}\.ts", filename) or not (running.directory / filename).is_file():
        raise HTTPException(status_code=404, detail="No such part")
    return FileResponse(running.directory / filename, media_type="video/mp2t", headers=_NO_CACHE)


def _audio_aac_response(video_id: str, *, cookies: bool, head_only: bool) -> Response:
    headers = {**_NO_CACHE, "Content-Type": "audio/aac"}
    if head_only:
        return Response(status_code=200, headers=headers)
    lowest = _audio(video_id, cookies=cookies) or _variants(video_id, cookies=cookies)[-1]
    command = [
        _ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", *_ffmpeg_input(lowest),
        "-vn", "-map", "0:a:0", "-c:a", "copy", "-f", "adts", "pipe:1",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def body() -> Iterator[bytes]:
        try:
            while chunk := process.stdout.read(_READ):
                yield chunk
        finally:
            process.kill()
            process.wait()

    return StreamingResponse(body(), headers=headers)


# --- Routes ----------------------------------------------------------------------------------------

def _profile(token: str) -> tuple[bool, list[tuple[str, str]]]:
    """Whether the profile's collection uses cookies, and its live episodes as (video id, title)."""
    with db_session() as s:
        profile = get_rss_stream_profile_by_token(s, token)
        live = (
            s.query(Episode)
            .filter(Episode.collection_id == profile.collection_id, Episode.publish_status == EpisodePublishStatus.LIVE.value)
            .all()
        )
        videos = []
        for episode in live:
            video_id = (re.search(r"[?&]v=([A-Za-z0-9_-]+)", episode.sharing_url or "") or [None, None])[1]
            if video_id:
                videos.append((video_id, episode.title))
        return uses_cookies(profile.collection), videos


def _video(video_id: str) -> str:
    if not _VIDEO_ID.match(video_id):
        raise HTTPException(status_code=404, detail="Not a YouTube video id")
    return video_id


@router.api_route("/rss/{token}/experiments/live/feed.xml", methods=["GET", "HEAD"])
def live_experiments_feed(token: str, request: Request, v: str | None = None):
    cookies, videos = _profile(token)
    if v:
        videos = []
        for video_id in v.split(","):
            video_id = _video(video_id.strip())
            try:
                title = _info(video_id, cookies=cookies).get("title") or video_id
            except HTTPException:
                title = video_id
            videos.append((video_id, title))

    base = f"{request_base_url(request)}/feeds/rss/{token}/experiments/live"
    register_namespace("itunes", _ITUNES)
    register_namespace("podcast", _PODCAST)
    rss = Element("rss", {"version": "2.0"})
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = "YouTube live experiments"
    SubElement(channel, "link").text = base
    SubElement(channel, "description").text = "Every live video once per streaming method, to see which ones play."
    SubElement(channel, "{%s}type" % _ITUNES).text = "episodic"
    now = datetime.now(timezone.utc)
    for video_id, title in videos:
        for index, (method, (label, filename, media_type)) in enumerate(METHODS.items()):
            item = SubElement(channel, "item")
            SubElement(item, "title").text = f"[{label}] {title}"
            SubElement(item, "guid", {"isPermaLink": "false"}).text = f"live-{video_id}-{method}"
            SubElement(item, "description").text = f"Method {method}."
            # A second apart, so apps keep the methods in order.
            SubElement(item, "pubDate").text = format_datetime(now - timedelta(seconds=index))
            SubElement(item, "{%s}episode" % _ITUNES).text = str(index + 1)
            url = f"{base}/{video_id}/{method}/{filename}"
            SubElement(item, "enclosure", {"url": url, "type": media_type, "length": "0"})
            if method == "feed-shape":
                alternate = SubElement(item, "{%s}alternateEnclosure" % _PODCAST, {
                    "type": "application/x-mpegURL", "length": "0", "title": "Live video", "rel": "alternate",
                })
                SubElement(alternate, "{%s}source" % _PODCAST, {"uri": f"{base}/{video_id}/direct/video.m3u8"})
    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(rss)
    return Response(
        content=b"" if request.method == "HEAD" else xml, media_type="application/rss+xml; charset=utf-8", headers=_NO_CACHE,
    )


@router.get("/rss/{token}/experiments/live/{video_id}/diagnose")
def live_experiments_diagnose(token: str, video_id: str):
    cookies, _videos = _profile(token)
    video_id = _video(video_id)
    report = {"url": _watch_url(video_id), "cookies": cookies, "clients": {}}
    for client in _CLIENTS:
        started = time.time()
        try:
            info = _info(video_id, client=client, cookies=cookies, fresh=True)
        except HTTPException as exc:
            report["clients"][client or "default"] = {"error": exc.detail, "seconds": round(time.time() - started, 1)}
            continue
        report["clients"][client or "default"] = {
            "seconds": round(time.time() - started, 1),
            "live_status": info.get("live_status"),
            "manifest": bool(info.get("manifest_url")),
            "variants": [
                {"id": fmt.get("format_id"), "height": fmt.get("height"), "vcodec": fmt.get("vcodec"), "acodec": fmt.get("acodec"),
                 "tbr": fmt.get("tbr")}
                for fmt in live_variants(info)
            ],
            "audio": [
                {"id": fmt.get("format_id"), "acodec": fmt.get("acodec"), "language": fmt.get("language"), "tbr": fmt.get("tbr")}
                for fmt in info.get("formats") or []
                if "m3u8" in str(fmt.get("protocol", "")) and (fmt.get("vcodec") or "none") == "none"
            ],
            "other_formats": sorted({str(fmt.get("protocol")) for fmt in info.get("formats") or []}),
        }
    return JSONResponse(report, headers=_NO_CACHE)


@router.get("/rss/{token}/experiments/live/{video_id}/check")
def live_experiments_check(token: str, video_id: str, request: Request):
    """Fetch every method's playlists and first segment from VODLoft itself, and say what each answered."""
    video_id = _video(video_id)
    base = f"{request_base_url(request)}/feeds/rss/{token}/experiments/live/{video_id}"
    report: dict[str, object] = {}

    def fetch(name: str, url: str, *, text: bool) -> str | None:
        started = time.time()
        try:
            response = requests.get(url, stream=True, timeout=60, allow_redirects=False)
            first = next(response.iter_content(2048 if text else 1024), b"")
            report[name] = {
                "status": response.status_code, "seconds": round(time.time() - started, 1),
                "type": response.headers.get("Content-Type"), "location": (response.headers.get("Location") or "")[:120] or None,
                "start": first[:400].decode(errors="replace") if text or response.status_code >= 400 else first[:8].hex(),
            }
            response.close()
            return first.decode(errors="replace") if text and response.status_code == 200 else None
        except Exception as exc:
            report[name] = {"error": str(exc)}
            return None

    fetch("redirect", f"{base}/redirect/video.m3u8", text=True)
    for method in ("direct", "proxy"):
        master = fetch(f"{method}/video.m3u8", f"{base}/{method}/video.m3u8", text=True) or ""
        audio = re.search(r'TYPE=AUDIO[^\n]*URI="([^"]+)"', master)
        variant = next((line for line in master.splitlines() if line and not line.startswith("#")), None)
        for kind, name in (("video", variant), ("audio", audio.group(1) if audio else None)):
            if name is None:
                continue
            playlist = fetch(f"{method}/{name}", f"{base}/{method}/{name}", text=True) or ""
            segment = next((line for line in playlist.splitlines() if line and not line.startswith("#")), None)
            if segment:
                fetch(f"{method}/first {kind} segment", urljoin(f"{base}/{method}/{name}", segment), text=False)
    fetch("audio-hls/audio.m3u8", f"{base}/audio-hls/audio.m3u8", text=True)
    started = time.time()
    try:
        with requests.get(f"{base}/audio-aac/audio.aac", stream=True, timeout=60) as response:
            received = 0
            for chunk in response.iter_content(_READ):
                received += len(chunk)
                if received >= 256 * 1024 or time.time() - started > 20:
                    break
            report["audio-aac/audio.aac"] = {"status": response.status_code, "bytes_in_20s": received,
                                             "seconds": round(time.time() - started, 1)}
    except Exception as exc:
        report["audio-aac/audio.aac"] = {"error": str(exc)}
    return JSONResponse(report, headers=_NO_CACHE)


@router.api_route("/rss/{token}/experiments/live/{video_id}/{method}/segment", methods=["GET", "HEAD"])
def live_experiments_segment(token: str, video_id: str, method: str, u: str, request: Request):
    """One segment of YouTube's live stream, passed on (method C)."""
    _profile(token)
    return _segment_response(u, range_header=request.headers.get("range"), head_only=request.method == "HEAD")


@router.api_route("/rss/{token}/experiments/live/{video_id}/{method}/{filename}", methods=["GET", "HEAD"])
def live_experiments_media(token: str, video_id: str, method: str, filename: str, request: Request):
    if method not in METHODS:
        raise HTTPException(status_code=404, detail="Unknown method")
    cookies, _videos = _profile(token)
    video_id = _video(video_id)
    head_only = request.method == "HEAD"
    logger.info("YouTube live experiment %s for %s: %s %s", method, video_id, request.method, filename)

    if method == "redirect":
        info = _info(video_id, cookies=cookies)
        manifest = info.get("manifest_url") or next((fmt.get("manifest_url") for fmt in live_variants(info) if fmt.get("manifest_url")), None)
        if not manifest:
            raise HTTPException(status_code=404, detail="No master playlist; see /diagnose")
        return RedirectResponse(manifest, status_code=302, headers=_NO_CACHE)
    if method in ("direct", "proxy"):
        if filename == "video.m3u8":
            master = master_playlist(_variants(video_id, cookies=cookies), _audio(video_id, cookies=cookies))
            return _playlist_response(master, head_only=head_only)
        match = re.fullmatch(r"variant-([\w-]+)\.m3u8", filename)
        if match is None:
            raise HTTPException(status_code=404, detail="No such playlist")
        proxy_base = str(request.url).split("?", 1)[0].rsplit("/", 1)[0] + "/segment" if method == "proxy" else None
        text = _variant_playlist(video_id, match.group(1), cookies=cookies, proxy_base=proxy_base)
        return _playlist_response(text, head_only=head_only)
    if method == "audio-hls":
        return _audio_hls_response(video_id, filename, cookies=cookies, head_only=head_only)
    return _audio_aac_response(video_id, cookies=cookies, head_only=head_only)
