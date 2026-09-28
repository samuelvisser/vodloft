"""One request per process: JSON on stdin, JSON on stdout, diagnostics on stderr."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yt_dlp
from source_contracts import (
    CollectionPage, DownloadResult, EntrySnapshot, MediaSnapshot, SourceManifest,
    SourceMatch, SourceMediaReference,
)
from source_contracts.network import install_public_network_guard


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


def resolve(url: str, *, max_entries: int = 100) -> MediaSnapshot:
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "playlistend": max_entries + 1, "skip_download": True}) as ydl:
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
            **({"published_at": published} if (published := _published(entry)) else {}),
        ))
    thumbnails = info.get("thumbnails") or []
    optional = {key: info[key] for key in ("description", "duration") if key in info}
    if info.get("thumbnail") or thumbnails:
        optional["artwork_url"] = info.get("thumbnail") or thumbnails[-1].get("url")
    if published := _published(info):
        optional["published_at"] = published
    return MediaSnapshot(
        kind=kind, reference=_reference(info, url),
        title=str(info.get("title") or info.get("id") or "Untitled"),
        entries=entries, enumeration_complete=len(raw_entries) <= max_entries, **optional,
    )


def entries(url: str, cursor: str | None = None, limit: int = 50) -> CollectionPage:
    if cursor is not None and (not cursor.isdecimal() or len(cursor) > 8):
        raise ValueError("Invalid Collection cursor")
    offset = int(cursor or "0")
    if offset > 100000 or not 1 <= limit <= 100:
        raise ValueError("Collection enumeration limit exceeded")
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
                           "playliststart": offset + 1, "playlistend": offset + limit + 1,
                           "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info or info.get("_type") not in ("playlist", "multi_video"):
        raise ValueError("This URL is not a Collection")
    raw = list(info.get("entries") or [])
    page = [EntrySnapshot(reference=_reference(item, url, strict=True),
        title=str(item.get("title") or item.get("id") or "Untitled"),
        position=offset + position + 1,
        kind="collection" if item.get("_type") == "playlist" else "video",
        **({"published_at": published} if (published := _published(item)) else {}))
        for position, item in enumerate(raw[:limit]) if item]
    has_more = len(raw) > limit
    return CollectionPage(entries=page, next_cursor=str(offset + limit) if has_more else None,
                          complete=not has_more)


def download(url: str, staging: str, preferred_format: str = "format_1080p") -> DownloadResult:
    destination = Path(staging).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if preferred_format == "format_audio_only":
        format_selector = "bestaudio/best"
        postprocessors = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
    else:
        height = {"format_720p": 720, "format_1080p": 1080, "format_4k": 2160}.get(preferred_format, 1080)
        format_selector = f"bestvideo*[height<={height}]+bestaudio/best[height<={height}]/best"
        postprocessors = []
    with yt_dlp.YoutubeDL({
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "outtmpl": str(destination / "media.%(ext)s"),
        "restrictfilenames": True,
        "format": format_selector,
        "hls_prefer_native": True,
        "postprocessors": postprocessors,
    }) as ydl:
        ydl.download([url])
    files = [p for p in destination.iterdir() if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
    if len(files) != 1:
        raise RuntimeError("Source did not produce exactly one completed media file")
    return DownloadResult(filename=files[0].name, size=files[0].stat().st_size)


def main() -> None:
    request = json.load(sys.stdin)
    operation = request["operation"]
    if operation in ("resolve", "download", "entries"):
        install_public_network_guard()
    if operation == "manifest":
        result = SourceManifest(source_id="yt-dlp", display_name="yt-dlp", version=yt_dlp.version.__version__,
                                capabilities={"resolve_url", "enumerate_collection", "enumerate_pages", "download", "domain_catalogue"})
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
        result = resolve(request["url"], max_entries=request.get("max_entries", 100))
    elif operation == "match":
        from yt_dlp.extractor import gen_extractor_classes
        matching = [extractor for extractor in gen_extractor_classes()
                    if extractor.suitable(request["url"])]
        specific = any(extractor.ie_key() != "Generic" for extractor in matching)
        result = SourceMatch(source_id="yt-dlp", confidence=60 if specific else 10,
                             reason="Supported extractor" if specific else "Generic URL candidate")
    elif operation == "entries":
        result = entries(request["url"], request.get("cursor"), request.get("limit", 50))
    elif operation == "download":
        result = download(request["url"], request["staging"], request.get("preferred_format", "format_1080p"))
    else:
        raise ValueError(f"Unsupported Source operation: {operation}")
    print(result.model_dump_json(exclude_unset=True) if hasattr(result, "model_dump_json") else json.dumps(result))


if __name__ == "__main__":
    main()
