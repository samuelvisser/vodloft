"""Daily Wire Source protocol over a one-request worker process."""

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import yt_dlp
from dailywire_api.dw_api.client import MiddlewareClient, DEFAULT_MIDDLEWARE_URL
from dailywire_api.dw_api.movie import MovieMiddlewareClient
from source_contracts import (DomainDescriptor, DownloadResult, EntrySnapshot,
                              MediaSnapshot, SourceManifest, SourceMediaReference)
from source_contracts.network import install_public_network_guard

SOURCE_ID = "dailywire"


def _client(token: str | None = None, movie: bool = False):
    klass = MovieMiddlewareClient if movie else MiddlewareClient
    return klass(access_token=token, base_url=DEFAULT_MIDDLEWARE_URL,
        pacing_settings=SimpleNamespace(min_fast_request_ms=100,
            min_slow_request_ms=120000, max_fast_requests=350),
        token_provider=lambda: token)


def _reference(kind: str, slug: str, upstream_id: str | None = None,
               sharing_url: str | None = None) -> SourceMediaReference:
    return SourceMediaReference(source_id=SOURCE_ID, domain="dailywire.com", namespace=kind,
        upstream_id=upstream_id or slug,
        url=sharing_url or f"https://www.dailywire.com/{kind}/{slug}")


def resolve(url: str, max_entries: int = 100, token: str | None = None) -> MediaSnapshot:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in {
        "dailywire.com", "www.dailywire.com"}:
        raise ValueError("Not a Daily Wire media URL")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2 or not re.fullmatch(r"[a-zA-Z0-9_-]+", parts[1]):
        raise ValueError("Unsupported Daily Wire media URL")
    kind, slug = parts
    client = _client(token)
    if kind in ("show", "shows"):
        record = client.get_show_page(slug)
        entries = [EntrySnapshot(reference=_reference("episode", e.slug, e.dw_id, e.sharing_url),
                                 title=e.title, position=index)
                   for index, e in enumerate(record.latest_episodes[:max_entries], 1)]
        return MediaSnapshot(kind="collection", reference=_reference("show", record.slug, record.dw_id,
            record.sharing_url), title=record.title, description=record.description,
            artwork_url=record.thumbnail_portrait_path or record.background_image_path,
            entries=entries, enumeration_complete=False)
    if kind in ("episode", "episodes"):
        record = client.get_episode_details(slug)
        return MediaSnapshot(kind="video", reference=_reference("episode", record.slug, record.dw_id,
            record.sharing_url), title=record.title, description=record.description,
            duration=record.duration, artwork_url=record.thumbnail_landscape_path)
    movie = _client(token, movie=True)
    if kind in ("videos", "movies"):
        record = movie.get_movie_page(slug)
        extras = [EntrySnapshot(reference=_reference("clips", extra.slug,
            extra.dw_id or extra.slug, extra.sharing_url), title=extra.title,
            position=index, kind="movie_extra", extra_type=extra.movie_extra_type)
            for index, extra in enumerate(record.movie_extras, 1)]
        return MediaSnapshot(kind="movie", reference=_reference("videos", record.slug, record.dw_id,
            record.sharing_url), title=record.title, description=record.description,
            duration=record.duration, artwork_url=record.thumbnail_portrait_path,
            extras=extras)
    if kind in ("clips", "clip"):
        detail = movie.get_movie_extra_playback(slug)
        record = detail.metadata
        return MediaSnapshot(kind="movie_extra", reference=_reference("clips", record.slug,
            record.dw_id or record.slug, record.sharing_url), title=record.title,
            description=record.description, duration=record.duration,
            artwork_url=record.thumbnail_landscape_path)
    raise ValueError("Unsupported Daily Wire media URL")


def download(url: str, staging: str, preferred_format: str = "format_1080p",
             token: str | None = None) -> DownloadResult:
    snapshot = resolve(url, token=token)
    if snapshot.kind == "collection":
        raise ValueError("Download a playable item, not a Collection")
    parsed = urlsplit(url)
    kind, slug = parsed.path.strip("/").split("/")
    if kind in ("episode", "episodes"):
        detail = _client(token).get_episode_details(slug)
        playback_url = detail.audio_url if preferred_format == "format_audio_only" else detail.video_url
    elif kind in ("clips", "clip"):
        playback_url = _client(token, movie=True).get_movie_extra_playback(slug).video_url
    else:
        playback_url = _client(token, movie=True).get_movie_playback(slug).video_url
    if not playback_url or urlsplit(playback_url).scheme != "https":
        raise ValueError("No compatible playback representation is available")
    destination = Path(staging).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    options = {"quiet": True, "no_warnings": True, "noplaylist": True,
               "outtmpl": str(destination / "media.%(ext)s"), "hls_prefer_native": True}
    if preferred_format == "format_audio_only":
        options.update(format="bestaudio/best", postprocessors=[{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}])
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([playback_url])
    files = [p for p in destination.iterdir() if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
    if len(files) != 1:
        raise RuntimeError("Daily Wire Source did not produce one completed file")
    return DownloadResult(filename=files[0].name, size=files[0].stat().st_size)


def main():
    request = json.load(sys.stdin)
    operation = request["operation"]
    if operation in ("resolve", "download"):
        install_public_network_guard()
    if operation == "manifest":
        result = SourceManifest(source_id=SOURCE_ID, display_name="Daily Wire API",
            version="0.1.0", capabilities={"resolve_url", "enumerate_collection", "download", "domain_catalogue"},
            exhaustive_domain_catalogue=True,
            configuration_schema=[{"name": "access_token", "label": "Access token", "kind": "secret",
                                   "required": False}])
    elif operation == "domains":
        result = {"items": [DomainDescriptor(hostname="dailywire.com", display_name="Daily Wire",
            source_id=SOURCE_ID).model_dump()], "next_cursor": None, "exhaustive": True,
            "supports_url_resolution_outside_catalog": False, "catalog_revision": "1"}
    elif operation == "resolve":
        result = resolve(request["url"], request.get("max_entries", 100), request.get("access_token"))
    elif operation == "download":
        result = download(request["url"], request["staging"], request.get("preferred_format", "format_1080p"),
                          request.get("access_token"))
    else:
        raise ValueError(f"Unsupported Source operation: {operation}")
    print(result.model_dump_json() if hasattr(result, "model_dump_json") else json.dumps(result))


if __name__ == "__main__":
    main()
