"""Daily Wire Source protocol over a one-request worker process."""

import base64
import binascii
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import yt_dlp
from dailywire_api.dw_api.client import ByNextPage, ByShowSeason, MiddlewareClient, DEFAULT_MIDDLEWARE_URL
from dailywire_api.dw_api.movie import MovieMiddlewareClient
from source_contracts import (CollectionPage, DomainDescriptor, DownloadResult, EntrySnapshot,
                              MediaSnapshot, SourceManifest, SourceMatch, SourceMediaReference)
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
                                 title=e.title, position=index, published_at=e.published_date,
                                 episode_number=e.episode_number or None)
                   for index, e in enumerate(record.latest_episodes[:max_entries], 1)]
        return MediaSnapshot(kind="collection", reference=_reference("show", record.slug, record.dw_id,
            record.sharing_url), title=record.title, description=record.description,
            artwork_url=record.thumbnail_portrait_path or record.background_image_path,
            entries=entries, enumeration_complete=False)
    if kind in ("episode", "episodes"):
        record = client.get_episode_details(slug)
        return MediaSnapshot(kind="video", reference=_reference("episode", record.slug, record.dw_id,
            record.sharing_url), title=record.title, description=record.description,
            duration=record.duration, artwork_url=record.thumbnail_landscape_path,
            published_at=record.published_date)
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


def entries(url: str, cursor: str | None = None, limit: int = 50,
            token: str | None = None) -> CollectionPage:
    parsed = urlsplit(url)
    parts = parsed.path.strip("/").split("/")
    if (parsed.hostname not in {"dailywire.com", "www.dailywire.com"} or
        parsed.scheme not in {"http", "https"} or len(parts) != 2 or
        parts[0] not in {"show", "shows"} or not re.fullmatch(r"[a-zA-Z0-9_-]+", parts[1]) or
        not 1 <= limit <= 100):
        raise ValueError("Invalid Daily Wire Collection enumeration")
    client = _client(token)
    show = client.get_show_page(parts[1])
    seasons = list(reversed(show.seasons))
    if not seasons:
        return CollectionPage(entries=[EntrySnapshot(reference=_reference("episode", e.slug, e.dw_id, e.sharing_url),
            title=e.title, position=index, published_at=e.published_date,
            episode_number=e.episode_number or None)
            for index, e in enumerate(show.latest_episodes[:limit], 1)],
            complete=False)
    if cursor and len(cursor) > 4096:
        raise ValueError("Invalid Collection cursor")
    try:
        state = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))) if cursor else {}
        season_index, position = int(state.get("season", 0)), int(state.get("position", 0))
        next_page = state.get("next")
        if (season_index < 0 or season_index >= len(seasons) or position < 0 or
            position > 100000 or not isinstance(next_page, (str, type(None))) or
            (next_page and (len(next_page) > 2000 or "getPaginatedEpisodes" not in urlsplit(next_page).path))):
            raise ValueError("Invalid Collection cursor")
    except (ValueError, TypeError, binascii.Error) as exc:
        raise ValueError("Invalid Collection cursor") from exc
    season = seasons[season_index]
    selector = ByNextPage(next_page) if next_page else ByShowSeason(
        season_dw_id=season.dw_id, page_size=min(limit, 50))
    result = client.get_episodes_paginated(parts[1], selector)
    snapshots = [EntrySnapshot(reference=_reference("episode", e.slug, e.dw_id, e.sharing_url),
        title=e.title, position=position + index, group=season.name,
        published_at=e.published_date, episode_number=e.episode_number or None)
        for index, e in enumerate(result.items, 1)]
    position += len(result.items)
    if result.has_next and result.next_page_url:
        state = {"season": season_index, "position": position, "next": result.next_page_url}
    elif season_index + 1 < len(seasons):
        state = {"season": season_index + 1, "position": position, "next": None}
    else:
        return CollectionPage(entries=snapshots, complete=True)
    encoded = base64.urlsafe_b64encode(json.dumps(state, separators=(",", ":")).encode()).decode().rstrip("=")
    return CollectionPage(entries=snapshots, next_cursor=encoded, complete=False)


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
    if operation in ("resolve", "download", "entries"):
        install_public_network_guard()
    if operation == "manifest":
        result = SourceManifest(source_id=SOURCE_ID, display_name="Daily Wire API",
            version="0.1.0", capabilities={"resolve_url", "enumerate_collection", "enumerate_pages", "download", "domain_catalogue"},
            exhaustive_domain_catalogue=True,
            configuration_schema=[{"name": "access_token", "label": "Access token", "kind": "secret",
                                   "required": False}])
    elif operation == "domains":
        result = {"items": [DomainDescriptor(hostname="dailywire.com", display_name="Daily Wire",
            source_id=SOURCE_ID).model_dump()], "next_cursor": None, "exhaustive": True,
            "supports_url_resolution_outside_catalog": False, "catalog_revision": "1"}
    elif operation == "resolve":
        result = resolve(request["url"], request.get("max_entries", 100), request.get("access_token"))
    elif operation == "match":
        parsed = urlsplit(request["url"])
        parts = parsed.path.strip("/").split("/")
        supported = (parsed.hostname in {"dailywire.com", "www.dailywire.com"} and
            len(parts) == 2 and parts[0] in {"show", "shows", "episode", "episodes",
                "videos", "movies", "clips", "clip"} and bool(re.fullmatch(r"[a-zA-Z0-9_-]+", parts[1])))
        result = SourceMatch(source_id=SOURCE_ID, confidence=100 if supported else 0,
                             reason="Daily Wire media path" if supported else "Not a Daily Wire media URL")
    elif operation == "entries":
        result = entries(request["url"], request.get("cursor"), request.get("limit", 50),
                         request.get("access_token"))
    elif operation == "download":
        result = download(request["url"], request["staging"], request.get("preferred_format", "format_1080p"),
                          request.get("access_token"))
    else:
        raise ValueError(f"Unsupported Source operation: {operation}")
    print(result.model_dump_json(exclude_unset=True) if hasattr(result, "model_dump_json") else json.dumps(result))


if __name__ == "__main__":
    main()
