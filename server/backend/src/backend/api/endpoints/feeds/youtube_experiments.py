"""EXPERIMENT: several ways of streaming YouTube video to podcast apps, side by side.

This module is for testing only and is not meant to be merged as it is. It adds a second feed next to
a stream profile's own feed, ``/feeds/rss/{token}/experiments/feed.xml``, that lists the newest episodes
once for every method below, so each method can be tried in a real podcast app. Every method plays
an episode that is not downloaded; none of them looks at downloads.

  A  redirect     302 to YouTube's 360p MP4 (format 18). Only works if YouTube does not lock the URL
                  to VODLoft's address.
  B  proxy        VODLoft passes format 18 on in 10 MB ranges (what PR #158 does).
  C  passthrough  VODLoft passes format 18 on with the player's own range, in one upstream request.
  D  client-*     Like C, but with format 18 looked up by another YouTube player client (tv, web_safari,
                  mweb, android_vr). The default client often needs a PO token, without which YouTube
                  leaves formats out or refuses their URLs.
  E  muxed        Like C, with the best MP4 that has sound up to 720p from any client.
  F  hls-direct   YouTube's own HLS stream with sound (from the ios or web_safari client), with its
                  segment URLs left pointing at YouTube.
  G  hls-proxy    Like F, with every playlist and segment passed on through VODLoft.
  H  remux-live   ffmpeg joins 720p H.264 video and M4A audio into a fragmented MP4 while it plays.
                  No size, no seeking.
  I  remux-file   ffmpeg joins them into a complete MP4 first (as The Daily Wire's MP4 is built), then
                  VODLoft serves that file with ranges. The first play waits until it is ready.

``/feeds/rss/{token}/experiments/{episode}/diagnose`` shows what each client returns for an episode.
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
import threading
import time
from collections.abc import Iterator
from datetime import timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit
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
_CLIENTS = ("tv", "web_safari", "mweb", "android_vr")
_HLS_CLIENTS = ("ios", "web_safari")
_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"

# method: (label, enclosure file name, MIME type)
METHODS: dict[str, tuple[str, str, str]] = {
    "redirect": ("A redirect to format 18", "video.mp4", "video/mp4"),
    "proxy": ("B proxy format 18 in ranges", "video.mp4", "video/mp4"),
    "passthrough": ("C pass format 18 through", "video.mp4", "video/mp4"),
    **{f"client-{client}": (f"D format 18 from {client}", "video.mp4", "video/mp4") for client in _CLIENTS},
    "muxed": ("E best MP4 with sound", "video.mp4", "video/mp4"),
    "hls-direct": ("F YouTube HLS, direct segments", "video.m3u8", "application/x-mpegURL"),
    "hls-proxy": ("G YouTube HLS through VODLoft", "video.m3u8", "application/x-mpegURL"),
    "remux-live": ("H remux while playing", "video.mp4", "video/mp4"),
    "remux-file": ("I remux to a file first", "video.mp4", "video/mp4"),
}


# --- Looking episodes up --------------------------------------------------------------------------

_infos: dict[tuple[str, str | None], tuple[float, dict]] = {}
_info_locks: dict[tuple[str, str | None], threading.Lock] = {}
_guard = threading.Lock()


def _info(url: str, client: str | None, *, cookies: bool) -> dict:
    """yt-dlp's info for the video, with one player client or yt-dlp's default ones, kept for an hour."""
    key = (url, client)
    with _guard:
        lock = _info_locks.setdefault(key, threading.Lock())
    with lock:
        kept = _infos.get(key)
        if kept is not None and kept[0] > time.time():
            return kept[1]
        args = ["--no-playlist"]
        if client:
            args += ["--extractor-args", f"youtube:player_client={client}"]
        try:
            info = ytdlp_runner.run_json(*args, url, cookies=cookies)
        except ytdlp_runner.YtDlpError as exc:
            raise HTTPException(status_code=502, detail=f"yt-dlp ({client or 'default'}): {exc}") from exc
        _infos[key] = (time.time() + _KEEP_SECONDS, info)
        return info


def _formats(info: dict) -> list[dict]:
    return [fmt for fmt in info.get("formats") or [] if fmt.get("url")]


def _has(fmt: dict, kind: str) -> bool:
    return (fmt.get(kind) or "none") != "none"


def _format_18(info: dict) -> dict | None:
    return next((fmt for fmt in _formats(info) if fmt.get("format_id") == "18"), None)


def _best_muxed_mp4(info: dict) -> dict | None:
    candidates = [
        fmt for fmt in _formats(info)
        if _has(fmt, "vcodec") and _has(fmt, "acodec") and fmt.get("ext") == "mp4"
        and str(fmt.get("protocol", "")).startswith("http") and (fmt.get("height") or 0) <= 720
    ]
    return max(candidates, key=lambda fmt: (fmt.get("height") or 0, fmt.get("tbr") or 0), default=None)


def _best_hls_with_sound(info: dict) -> dict | None:
    candidates = [
        fmt for fmt in _formats(info)
        if _has(fmt, "vcodec") and _has(fmt, "acodec") and "m3u8" in str(fmt.get("protocol", ""))
        and (fmt.get("height") or 0) <= 720
    ]
    return max(candidates, key=lambda fmt: (fmt.get("height") or 0, fmt.get("tbr") or 0), default=None)


def _video_for_remux(info: dict) -> dict | None:
    candidates = [
        fmt for fmt in _formats(info)
        if _has(fmt, "vcodec") and not _has(fmt, "acodec") and str(fmt.get("vcodec", "")).startswith("avc1")
        and str(fmt.get("protocol", "")).startswith("http") and (fmt.get("height") or 0) <= 720
    ]
    return max(candidates, key=lambda fmt: (fmt.get("height") or 0, fmt.get("tbr") or 0), default=None)


def _audio_m4a(info: dict) -> dict | None:
    return next((fmt for fmt in _formats(info) if fmt.get("format_id") == "140"), None) or next(
        (fmt for fmt in _formats(info) if not _has(fmt, "vcodec") and fmt.get("ext") == "m4a"
         and str(fmt.get("protocol", "")).startswith("http")), None,
    )


def _pick(info: dict, method: str) -> dict:
    if method in ("redirect", "proxy", "passthrough") or method.startswith("client-"):
        chosen = _format_18(info)
    elif method == "muxed":
        chosen = _best_muxed_mp4(info)
    else:
        chosen = _best_hls_with_sound(info)
    if chosen is None:
        raise HTTPException(status_code=404, detail=f"No format for method {method}; see /diagnose")
    return chosen


def _first_with(url: str, clients, pick, *, cookies: bool) -> tuple[dict, dict]:
    """The first client whose info has a format ``pick`` finds, with that format."""
    errors = []
    for client in clients:
        try:
            info = _info(url, client, cookies=cookies)
        except Exception as exc:
            errors.append(f"{client}: {exc}")
            continue
        chosen = pick(info)
        if chosen is not None:
            return info, chosen
        errors.append(f"{client}: no suitable format")
    raise HTTPException(status_code=404, detail="; ".join(errors))


# --- Passing bytes on ------------------------------------------------------------------------------

def _headers_of(fmt: dict) -> dict[str, str]:
    return {str(name): str(value) for name, value in (fmt.get("http_headers") or {}).items()}


def _media_headers(media_type: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    return {**_NO_CACHE, "Accept-Ranges": "bytes", "Content-Type": media_type, **(extra or {})}


def _passthrough(fmt: dict, *, range_header: str | None, head_only: bool, media_type: str) -> Response:
    """One upstream request with the player's own range; YouTube's status and size are passed on."""
    headers = _headers_of(fmt)
    if range_header:
        headers["Range"] = range_header
    upstream = requests.get(fmt["url"], headers=headers, stream=True, timeout=_TIMEOUT)
    if upstream.status_code not in (200, 206):
        upstream.close()
        raise HTTPException(status_code=502, detail=f"YouTube answered {upstream.status_code}")
    passed = {name: upstream.headers[name] for name in ("Content-Length", "Content-Range") if name in upstream.headers}
    response_headers = _media_headers(media_type, passed)
    if head_only:
        upstream.close()
        return Response(status_code=upstream.status_code, headers=response_headers)

    def body() -> Iterator[bytes]:
        try:
            yield from upstream.iter_content(_READ)
        finally:
            upstream.close()

    return StreamingResponse(body(), status_code=upstream.status_code, headers=response_headers)


def _chunked(fmt: dict, *, range_header: str | None, head_only: bool) -> Response:
    """PR #158's way: YouTube in 10 MB ranges, whatever the player asked for."""
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    start, end = 0, None
    if range_header and range_header.startswith("bytes="):
        first, _, last = range_header.removeprefix("bytes=").partition("-")
        start = int(first or 0)
        end = int(last) if last else None
    if size:
        end = min(end, size - 1) if end is not None else size - 1
    length = (end - start + 1) if end is not None else None
    extra = {}
    if length is not None:
        extra["Content-Length"] = str(length)
    if range_header and size:
        extra["Content-Range"] = f"bytes {start}-{end}/{size}"
    status = 206 if range_header else 200
    headers = _media_headers("video/mp4", extra)
    if head_only:
        return Response(status_code=status, headers=headers)

    def body() -> Iterator[bytes]:
        position = start
        while end is None or position <= end:
            last = position + _UPSTREAM_CHUNK - 1
            if end is not None:
                last = min(last, end)
            upstream = requests.get(
                fmt["url"], headers={**_headers_of(fmt), "Range": f"bytes={position}-{last}"}, stream=True, timeout=_TIMEOUT,
            )
            try:
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

    return StreamingResponse(body(), status_code=status, headers=headers)


# --- HLS -------------------------------------------------------------------------------------------

_ALLOWED_HOSTS = ("googlevideo.com", "youtube.com", "ytimg.com")


def _allowed(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in _ALLOWED_HOSTS)


def _rewrite_playlist(text: str, base_url: str, proxy) -> str:
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


def _hls_response(fmt: dict, *, proxy_base: str | None, head_only: bool) -> Response:
    playlist_url = fmt["url"]
    upstream = requests.get(playlist_url, headers=_headers_of(fmt), timeout=_TIMEOUT)
    if upstream.status_code != 200:
        raise HTTPException(status_code=502, detail=f"YouTube answered {upstream.status_code} for the playlist")
    proxy = (lambda url: f"{proxy_base}?u={quote(url, safe='')}") if proxy_base else None
    # YouTube's playlist of this one format; AVPlayer also plays a media playlist without a master.
    body = _rewrite_playlist(upstream.text, playlist_url, proxy)
    content = body.encode()
    headers = {**_NO_CACHE, "Content-Type": "application/x-mpegURL", "Content-Length": str(len(content))}
    return Response(content=b"" if head_only else content, headers=headers)


# --- Remuxing --------------------------------------------------------------------------------------

def _ffmpeg_inputs(*formats: dict) -> list[str]:
    command = []
    for fmt in formats:
        headers = _headers_of(fmt)
        agent = headers.pop("User-Agent", None)
        if agent:
            command += ["-user_agent", agent]
        if headers:
            command += ["-headers", "".join(f"{name}: {value}\r\n" for name, value in headers.items())]
        command += ["-i", fmt["url"]]
    return command


def _remux_live(video: dict, audio: dict, *, head_only: bool) -> Response:
    headers = {**_NO_CACHE, "Content-Type": "video/mp4"}
    if head_only:
        return Response(status_code=200, headers=headers)
    command = [
        get_settings().download_settings.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-nostdin",
        *_ffmpeg_inputs(video, audio), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", "pipe:1",
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


_file_locks: dict[str, threading.Lock] = {}


def _remux_file(episode_uuid: str, video: dict, audio: dict) -> Path:
    root = Path(get_settings().download_settings.rss_cache_root) / "youtube-experiment"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{hashlib.sha256(episode_uuid.encode()).hexdigest()[:24]}.mp4"
    with _guard:
        lock = _file_locks.setdefault(str(path), threading.Lock())
    with lock:
        if path.is_file():
            return path
        temporary = path.with_suffix(".partial.mp4")
        command = [
            get_settings().download_settings.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            *_ffmpeg_inputs(video, audio), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
            "-movflags", "+faststart", str(temporary),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60 * 60)
        if result.returncode != 0:
            temporary.unlink(missing_ok=True)
            raise HTTPException(status_code=502, detail=f"ffmpeg failed: {result.stderr[-500:]}")
        temporary.replace(path)
        return path


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
        items = [
            (episode.slug, episode.title, episode.published_date, episode.duration, episode.description)
            for episode in _episodes(s, profile, max(1, min(episodes, 10)))
        ]
        title = collection.title

    base = f"{request_base_url(request)}/feeds/rss/{token}/experiments"
    register_namespace("itunes", _ITUNES)
    rss = Element("rss", {"version": "2.0"})
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = f"{title} (YouTube experiments)"
    SubElement(channel, "link").text = base
    SubElement(channel, "description").text = "Every episode once per streaming method, to see which ones play."
    SubElement(channel, "{%s}type" % _ITUNES).text = "episodic"
    for slug, episode_title, published, duration, description in items:
        for index, (method, (label, filename, media_type)) in enumerate(METHODS.items()):
            item = SubElement(channel, "item")
            SubElement(item, "title").text = f"[{label}] {episode_title}"
            SubElement(item, "guid", {"isPermaLink": "false"}).text = f"{slug}-{method}"
            SubElement(item, "description").text = f"Method {method}. {description or ''}"
            if published is not None:
                # A second apart, so apps keep the methods in order.
                published_at = published if published.tzinfo else published.replace(tzinfo=timezone.utc)
                SubElement(item, "pubDate").text = format_datetime(published_at - timedelta(seconds=index))
            if duration:
                SubElement(item, "{%s}duration" % _ITUNES).text = str(int(duration))
            SubElement(item, "{%s}episode" % _ITUNES).text = str(index + 1)
            SubElement(item, "enclosure", {"url": f"{base}/{slug}/{method}/{filename}", "type": media_type, "length": "0"})
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
    url, _uuid, cookies = _episode(token, episode_slug)
    report = {"url": url, "cookies": cookies, "clients": {}}
    for client in (None, *_CLIENTS, *[c for c in _HLS_CLIENTS if c not in _CLIENTS]):
        name = client or "default"
        started = time.time()
        try:
            info = _info(url, client, cookies=cookies)
        except Exception as exc:
            report["clients"][name] = {"error": str(exc), "seconds": round(time.time() - started, 1)}
            continue
        report["clients"][name] = {
            "seconds": round(time.time() - started, 1),
            "format_18": bool(_format_18(info)),
            "best_muxed_mp4": (_best_muxed_mp4(info) or {}).get("format_id"),
            "best_hls_with_sound": (_best_hls_with_sound(info) or {}).get("format_id"),
            "remux_video": (_video_for_remux(info) or {}).get("format_id"),
            "m4a_audio": (_audio_m4a(info) or {}).get("format_id"),
            "formats": [
                {
                    "id": fmt.get("format_id"), "ext": fmt.get("ext"), "protocol": fmt.get("protocol"),
                    "vcodec": fmt.get("vcodec"), "acodec": fmt.get("acodec"), "height": fmt.get("height"),
                    "size": fmt.get("filesize") or fmt.get("filesize_approx"),
                    "url_host": urlsplit(fmt["url"]).hostname,
                }
                for fmt in _formats(info)
            ],
        }
    return JSONResponse(report, headers=_NO_CACHE)


@router.get("/rss/{token}/experiments/{episode_slug}/check")
def experiments_check(token: str, episode_slug: str, request: Request):
    """Ask every method for its first bytes from VODLoft itself, and say what each one answered."""
    base = f"{request_base_url(request)}/feeds/rss/{token}/experiments/{episode_slug}"
    report = {}
    for method, (_label, filename, _type) in METHODS.items():
        if method == "remux-file":
            report[method] = "skipped: builds the whole file first"
            continue
        started = time.time()
        try:
            response = requests.get(
                f"{base}/{method}/{filename}", headers={"Range": "bytes=0-1023"}, stream=True, timeout=120,
                allow_redirects=False,
            )
            first = next(response.iter_content(1024), b"")
            report[method] = {
                "status": response.status_code, "seconds": round(time.time() - started, 1),
                "content_type": response.headers.get("Content-Type"), "length": response.headers.get("Content-Length"),
                "range": response.headers.get("Content-Range"), "location": response.headers.get("Location"),
                "first_bytes": first[:12].hex(), "detail": first[:300].decode(errors="replace") if response.status_code >= 400 else None,
            }
            response.close()
        except Exception as exc:
            report[method] = {"error": str(exc)}
    return JSONResponse(report, headers=_NO_CACHE)


@router.api_route("/rss/{token}/experiments/{episode_slug}/{method}/segment", methods=["GET", "HEAD"])
def experiments_segment(token: str, episode_slug: str, method: str, u: str, request: Request):
    """A playlist or segment of YouTube's HLS stream, passed on (method G)."""
    _episode(token, episode_slug)
    if not _allowed(u):
        raise HTTPException(status_code=400, detail="Not a YouTube address")
    parts = urlsplit(u)
    if parts.path.endswith(".m3u8") or "playlist" in parts.path or (parts.hostname or "").startswith("manifest."):
        upstream = requests.get(u, timeout=_TIMEOUT)
        if upstream.status_code != 200:
            raise HTTPException(status_code=502, detail=f"YouTube answered {upstream.status_code}")
        proxy_base = str(request.url).split("?", 1)[0]
        text = _rewrite_playlist(upstream.text, u, lambda url: f"{proxy_base}?u={quote(url, safe='')}")
        return Response(content=text.encode(), headers={**_NO_CACHE, "Content-Type": "application/x-mpegURL"})
    return _passthrough({"url": u}, range_header=request.headers.get("range"), head_only=request.method == "HEAD",
                        media_type="video/mp2t" if u.endswith(".ts") else "video/mp4")


@router.api_route("/rss/{token}/experiments/{episode_slug}/{method}/{filename}", methods=["GET", "HEAD"])
def experiments_media(token: str, episode_slug: str, method: str, filename: str, request: Request):
    if method not in METHODS:
        raise HTTPException(status_code=404, detail="Unknown method")
    url, uuid, cookies = _episode(token, episode_slug)
    head_only = request.method == "HEAD"
    range_header = request.headers.get("range")
    logger.info("YouTube experiment %s for %s: %s %s", method, episode_slug, request.method, range_header)

    if method in ("redirect", "proxy", "passthrough", "muxed"):
        info = _info(url, None, cookies=cookies)
        fmt = _pick(info, method)
        if method == "redirect":
            return RedirectResponse(fmt["url"], status_code=302, headers=_NO_CACHE)
        if method == "proxy":
            return _chunked(fmt, range_header=range_header, head_only=head_only)
        return _passthrough(fmt, range_header=range_header, head_only=head_only, media_type="video/mp4")
    if method.startswith("client-"):
        fmt = _pick(_info(url, method.removeprefix("client-"), cookies=cookies), method)
        return _passthrough(fmt, range_header=range_header, head_only=head_only, media_type="video/mp4")
    if method in ("hls-direct", "hls-proxy"):
        _info_, fmt = _first_with(url, _HLS_CLIENTS, _best_hls_with_sound, cookies=cookies)
        proxy_base = str(request.url).rsplit("/", 1)[0] + "/segment" if method == "hls-proxy" else None
        return _hls_response(fmt, proxy_base=proxy_base, head_only=head_only)

    # Remuxing: video and audio from the first client that has both.
    info, video = _first_with(url, (None, *_CLIENTS), _video_for_remux, cookies=cookies)
    audio = _audio_m4a(info)
    if audio is None:
        raise HTTPException(status_code=404, detail="No M4A audio to remux with")
    if method == "remux-live":
        return _remux_live(video, audio, head_only=head_only)
    path = _remux_file(uuid, video, audio)
    return FileResponse(path, media_type="video/mp4", filename=f"{episode_slug}.mp4", content_disposition_type="inline", headers=_NO_CACHE)
