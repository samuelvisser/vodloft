"""One request per process: JSON on stdin, JSON on stdout, diagnostics on stderr."""

import json
import errno
import hashlib
import sys
import shutil
import subprocess
import tempfile
from urllib.error import HTTPError
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError
from source_contracts import (
    CollectionPage, DownloadResult, EntrySnapshot, MediaSnapshot, SourceError, SourceManifest,
    SourceMatch, SourceMediaReference, StreamLease,
)
from source_contracts.network import install_public_network_guard, fetch_stream
from vodloft_source_media import download as acquire_media, UnsupportedRepresentation, lease_expiry


@contextmanager
def _cookie_options(cookies: str | None, scratch: str | None = None):
    if not cookies:
        yield {}
        return
    if (len(cookies.encode()) > 1024 * 1024 or "\x00" in cookies or
        not cookies.lstrip("\ufeff").startswith(("# Netscape HTTP Cookie File", "# HTTP Cookie File"))):
        raise ValueError("Upload a Netscape-format cookies.txt file")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="vodloft-cookies-",
                                     suffix=".txt", dir=scratch, delete=False) as output:
        output.write(cookies.lstrip("\ufeff"))
        path = Path(output.name)
    try:
        yield {"cookiefile": str(path)}
    finally:
        path.unlink(missing_ok=True)


def _published(info: dict) -> datetime | None:
    timestamp = info.get("timestamp") or info.get("release_timestamp")
    if isinstance(timestamp, (int, float)) and timestamp > 0:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    raw = info.get("upload_date") or info.get("release_date")
    if isinstance(raw, str) and len(raw) == 8 and raw.isdigit():
        try:
            return datetime.strptime(raw, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _reference(info: dict, fallback_url: str, *, strict: bool = False) -> SourceMediaReference:
    url = info.get("webpage_url") or info.get("original_url") or info.get("url") or fallback_url
    if not url.startswith(("http://", "https://")):
        # yt-dlp's flat YouTube entries commonly expose only their video ID.
        if info.get("ie_key") == "Youtube" and info.get("id"):
            url = f"https://www.youtube.com/watch?v={info['id']}"
        elif strict:
            raise ValueError("Collection entry has no resolvable media URL")
        else:
            url = fallback_url
    domain = (urlsplit(url).hostname or urlsplit(fallback_url).hostname or "").lower().removeprefix("www.")
    if domain in {"youtu.be", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"}:
        domain = "youtube.com"
    return SourceMediaReference(
        source_id="yt-dlp", domain=domain,
        namespace=str(info.get("extractor_key") or info.get("ie_key") or "generic"),
        upstream_id=str(info.get("id") or url), url=url,
    )


def resolve(url: str, *, max_entries: int = 100, cookies: str | None = None,
            scratch: str | None = None) -> MediaSnapshot:
    with _cookie_options(cookies, scratch) as auth, yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
            "extract_flat": "in_playlist", "playlistend": max_entries + 1,
            "skip_download": True, **auth}) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise ValueError("No media was found at this URL")
    kind = "collection" if info.get("_type") in ("playlist", "multi_video") else "video"
    raw_entries = list(info.get("entries") or []) if kind == "collection" else []
    entries = []
    for position, entry in enumerate(raw_entries[:max_entries], start=1):
        if not entry:
            continue
        entries.append(EntrySnapshot(
            reference=_reference(entry, url, strict=True), title=str(entry.get("title") or entry.get("id") or "Untitled"),
            position=position, kind="collection" if entry.get("_type") == "playlist" else "video",
            capabilities={"enumerate_collection"} if entry.get("_type") == "playlist" else {"download"},
            **({"published_at": published} if (published := _published(entry)) else {}),
        ))
    thumbnails = info.get("thumbnails") or []
    optional = {key: info[key] for key in ("description", "duration") if key in info}
    if info.get("thumbnail") or thumbnails:
        optional["artwork_url"] = info.get("thumbnail") or thumbnails[-1].get("url")
    if published := _published(info):
        optional["published_at"] = published
    if kind != "collection":
        optional["chapters"] = [{"title": str(chapter.get("title") or "Chapter"),
            "start": max(0, chapter.get("start_time") or 0), "end": chapter.get("end_time")}
            for chapter in (info.get("chapters") or [])[:1000]]
        optional["tracks"] = [{"kind": "audio", "language": language}
            for language in sorted({fmt["language"] for fmt in info.get("formats") or []
                if isinstance(fmt, dict) and fmt.get("language")})][:80] + [
            {"kind": "subtitle", "language": language}
            for language in sorted(info.get("subtitles") or {})][:20]
        optional["is_live"] = bool(info.get("is_live") or info.get("live_status") == "is_live")
        heights = [fmt.get("height") for fmt in info.get("formats") or []
                   if isinstance(fmt, dict) and isinstance(fmt.get("height"), int)]
        maximum = max(heights, default=int(info.get("height") or 0))
        optional["formats"] = ([{"code": "format_audio_only", "audio_only": True,
            "container": "mp3", "description": "Audio MP3"}] + [
            {"code": code, "height": height, "description": f"Video up to {height}p"}
            for code, height in (("format_720p", 720), ("format_1080p", 1080),
                                 ("format_4k", 2160)) if maximum == 0 or maximum >= height])
    optional["author"] = info.get("uploader") or info.get("creator")
    optional["artwork"] = [{"url": image["url"],
        "role": "square" if image.get("width") and image.get("width") == image.get("height") else
                "portrait" if image.get("height", 0) > image.get("width", 0) else "landscape",
        "width": image.get("width") or None, "height": image.get("height") or None}
        for image in thumbnails[-50:] if image.get("url")]
    return MediaSnapshot(
        kind=kind, reference=_reference(info, url),
        title=str(info.get("title") or info.get("id") or "Untitled"),
        entries=entries, enumeration_complete=len(raw_entries) <= max_entries,
        capabilities={"enumerate_collection"} if kind == "collection" else {"download", "stream_lease"}, **optional,
    )


def entries(url: str, cursor: str | None = None, limit: int = 50,
            cookies: str | None = None, scratch: str | None = None) -> CollectionPage:
    if cursor is not None and (not cursor.isdecimal() or len(cursor) > 8):
        raise ValueError("Invalid Collection cursor")
    offset = int(cursor or "0")
    if offset > 100000 or not 1 <= limit <= 100:
        raise ValueError("Collection enumeration limit exceeded")
    with _cookie_options(cookies, scratch) as auth, yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
                           "playliststart": offset + 1, "playlistend": offset + limit + 1,
                           "skip_download": True, **auth}) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info or info.get("_type") not in ("playlist", "multi_video"):
        raise ValueError("This URL is not a Collection")
    raw = list(info.get("entries") or [])
    page = [EntrySnapshot(reference=_reference(item, url, strict=True),
        title=str(item.get("title") or item.get("id") or "Untitled"),
        position=offset + position + 1,
        kind="collection" if item.get("_type") == "playlist" else "video",
        capabilities={"enumerate_collection"} if item.get("_type") == "playlist" else {"download"},
        **({"published_at": published} if (published := _published(item)) else {}))
        for position, item in enumerate(raw[:limit]) if item]
    has_more = len(raw) > limit
    return CollectionPage(entries=page, next_cursor=str(offset + limit) if has_more else None,
                          complete=not has_more)


def download(url: str, staging: str, preferred_format: str = "format_1080p",
             cookies: str | None = None, scratch: str | None = None,
             representation: dict | None = None, metadata: dict | None = None,
             reference: dict | None = None) -> DownloadResult:
    expected = SourceMediaReference.model_validate(reference) if reference else None
    def verify(info):
        actual = _reference(info, url)
        if expected and any(getattr(expected, field) != getattr(actual, field)
                            for field in ("source_id", "domain", "namespace", "upstream_id")):
            raise ValueError("The Source URL now identifies different media")
    with _cookie_options(cookies, scratch) as auth:
        return acquire_media(url, staging, preferred_format, representation, metadata, auth, verify)


def stream_lease(url: str, cookies: str | None = None, scratch: str | None = None) -> StreamLease:
    """Resolve one direct transport; mixed adaptive formats need a local remux."""
    with _cookie_options(cookies, scratch) as auth, yt_dlp.YoutubeDL({
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "format": "best[protocol=https]/best[protocol=http]/best",
        "skip_download": True, **auth,
    }) as ydl:
        info = ydl.extract_info(url, download=False)
        private_cookie = ydl.cookiejar.get_cookie_header(info.get("url", "")) if info else None
    if not info or info.get("_type") == "playlist" or info.get("requested_formats"):
        raise ValueError("This item needs a prepared local streaming rendition")
    media_url = info.get("url")
    if not isinstance(media_url, str) or urlsplit(media_url).scheme != "https":
        raise ValueError("No safe direct streaming representation")
    protocol = str(info.get("protocol") or "")
    if protocol not in {"https", "http", "m3u8", "m3u8_native"}:
        raise ValueError("This transport requires a prepared local rendition")
    headers = {key: value for key, value in (info.get("http_headers") or {}).items()
               if key.lower() in {"user-agent", "referer", "origin", "cookie"} and
               isinstance(value, str) and len(value) < 8192}
    if private_cookie:
        headers["Cookie"] = private_cookie
    identity = hashlib.sha256(json.dumps({key: info.get(key) for key in
        ("id", "format_id", "vcodec", "acodec", "height", "duration", "filesize")}, sort_keys=True).encode()).hexdigest()
    return StreamLease(transport="hls" if "m3u8" in protocol else "http", url=media_url,
        renewable=True, seekable=True, headers=headers,
        expires_at=lease_expiry(media_url), representation_id=identity)


def main() -> None:
    request = json.load(sys.stdin)
    operation = request["operation"]
    if operation in ("resolve", "download", "entries", "stream_lease", "stream_fetch"):
        install_public_network_guard()
    if operation == "manifest":
        result = SourceManifest(source_id="yt-dlp", display_name="yt-dlp", version="1.0.1", upstream_versions={"yt-dlp": yt_dlp.version.__version__},
                                native_helpers=["ffmpeg"], catalogue_revision=yt_dlp.version.__version__,
                                capabilities={"health", "resolve_url", "enumerate_collection", "enumerate_pages", "download", "domain_catalogue", "stream_lease"},
                                configuration_schema=[{"name": "cookies", "label": "Netscape cookies.txt",
                                                       "kind": "credential_file"}])
    elif operation == "health":
        result = {"healthy": bool(shutil.which("ffmpeg")), "protocol_version": 1}
        if result["healthy"]:
            subprocess.run(["ffmpeg", "-version"], timeout=10, check=True, capture_output=True)
    elif operation == "domains":
        # This is deliberately a discoverable subset. Generic extractors and
        # embeds can resolve additional sites beyond any advertised catalogue.
        from yt_dlp.extractor import gen_extractor_classes
        extractors = {klass.ie_key() for klass in gen_extractor_classes()}
        domains = {"youtube.com": ("YouTube", "Youtube", ["youtu.be", "m.youtube.com"]),
                   "vimeo.com": ("Vimeo", "Vimeo", []),
                   "twitch.tv": ("Twitch", "Twitch", []),
                   "soundcloud.com": ("SoundCloud", "Soundcloud", []),
                   "dailymotion.com": ("Dailymotion", "Dailymotion", []),
                   "rumble.com": ("Rumble", "Rumble", []),
                   "bilibili.com": ("Bilibili", "BiliBili", []),
                   "tiktok.com": ("TikTok", "TikTok", []),
                   "instagram.com": ("Instagram", "Instagram", [])}
        result = {"items": [{"hostname": domain, "display_name": name, "source_id": "yt-dlp",
                             "support": "advertised", "aliases": aliases}
                            for domain, (name, key, aliases) in domains.items() if key in extractors],
                  "next_cursor": None, "exhaustive": False,
                  "supports_url_resolution_outside_catalog": True,
                  "catalog_revision": yt_dlp.version.__version__}
    elif operation == "resolve":
        result = resolve(request["url"], max_entries=request.get("max_entries", 100),
                         cookies=request.get("cookies"), scratch=request.get("scratch"))
    elif operation == "match":
        from yt_dlp.extractor import gen_extractor_classes
        matching = [extractor for extractor in gen_extractor_classes()
                    if extractor.suitable(request["url"])]
        specific = any(extractor.ie_key() != "Generic" for extractor in matching)
        result = SourceMatch(source_id="yt-dlp", confidence=60 if specific else 10,
                             reason="Supported extractor" if specific else "Generic URL candidate")
    elif operation == "entries":
        result = entries(request["url"], request.get("cursor"), request.get("limit", 50),
                         request.get("cookies"), request.get("scratch"))
    elif operation == "download":
        result = download(request["url"], request["staging"], request.get("preferred_format", "format_1080p"),
                          request.get("cookies"), request.get("scratch"), request.get("representation"), request.get("metadata"), request.get("reference"))
    elif operation == "stream_lease":
        result = stream_lease(request["url"], request.get("cookies"), request.get("scratch"))
    elif operation == "stream_fetch":
        result = fetch_stream(request["url"], request.get("headers"), request.get("byte_range"))
    else:
        print(json.dumps({"error": SourceError(code="unsupported_operation", message="This Source does not support the requested operation").model_dump()}))
        return
    print(result.model_dump_json(exclude_unset=True) if hasattr(result, "model_dump_json") else json.dumps(result))


def _source_error(exc: Exception) -> SourceError:
    if isinstance(exc, HTTPError) and exc.code in (401, 403, 429):
        code = "rate_limited" if exc.code == 429 else "authentication_required"
        message = "Source rate limit reached" if code == "rate_limited" else "Source authorization is required"
    elif isinstance(exc, PermissionError):
        code, message = "authentication_required", "Source authorization is required"
    elif isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        code, message = "insufficient_disk", "Insufficient staging disk space"
    elif isinstance(exc, UnsupportedRepresentation):
        code, message = "unsupported_format", "The requested representation is unavailable"
    elif isinstance(exc, ExtractorError):
        code = "unavailable" if exc.expected else "extraction_failed"
        message = "Source operation failed" if exc.expected else "yt-dlp extractor failed"
    elif isinstance(exc, DownloadError):
        # yt-dlp adds this text only to unexpected extractor failures. Inspect
        # it for classification, but never expose the upstream diagnostic.
        unexpected = "please report this issue on" in str(exc).casefold()
        code = "extraction_failed" if unexpected else "unavailable"
        message = "yt-dlp extractor failed" if unexpected else "Source operation failed"
    elif isinstance(exc, ValueError):
        code = "unsupported_operation" if str(exc).startswith("Unsupported Source operation") else "invalid_url"
        message = "Source operation is unsupported" if code == "unsupported_operation" else "Source URL or media reference is invalid"
    else:
        code, message = "unavailable", "Source operation failed"
    return SourceError(code=code, message=message)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": _source_error(exc).model_dump()}))
