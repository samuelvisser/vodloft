"""One request per process: JSON on stdin, JSON on stdout, diagnostics on stderr."""

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yt_dlp
from source_contracts import (
    DownloadResult, EntrySnapshot, MediaSnapshot, SourceManifest,
    SourceMediaReference,
)
from source_contracts.network import install_public_network_guard


def _reference(info: dict, fallback_url: str) -> SourceMediaReference:
    url = info.get("webpage_url") or info.get("original_url") or info.get("url") or fallback_url
    if not url.startswith(("http://", "https://")):
        # yt-dlp's flat YouTube entries commonly expose only their video ID.
        if info.get("ie_key") == "Youtube" and info.get("id"):
            url = f"https://www.youtube.com/watch?v={info['id']}"
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
            reference=_reference(entry, url), title=str(entry.get("title") or entry.get("id") or "Untitled"),
            position=position,
        ))
    thumbnails = info.get("thumbnails") or []
    return MediaSnapshot(
        kind=kind, reference=_reference(info, url),
        title=str(info.get("title") or info.get("id") or "Untitled"),
        description=info.get("description"), duration=info.get("duration"),
        artwork_url=info.get("thumbnail") or (thumbnails[-1].get("url") if thumbnails else None),
        entries=entries, enumeration_complete=len(raw_entries) <= max_entries,
    )


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
    if operation in ("resolve", "download"):
        install_public_network_guard()
    if operation == "manifest":
        result = SourceManifest(source_id="yt-dlp", display_name="yt-dlp", version=yt_dlp.version.__version__,
                                capabilities={"resolve_url", "enumerate_collection", "download", "domain_catalogue"})
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
    elif operation == "download":
        result = download(request["url"], request["staging"], request.get("preferred_format", "format_1080p"))
    else:
        raise ValueError(f"Unsupported Source operation: {operation}")
    print(result.model_dump_json() if hasattr(result, "model_dump_json") else json.dumps(result))


if __name__ == "__main__":
    main()
