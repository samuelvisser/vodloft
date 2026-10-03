"""Daily Wire Source protocol over a one-request worker process."""

import base64
import binascii
import errno
import hashlib
import json
import re
import sys
import uuid
import shutil
import subprocess
from urllib.error import HTTPError
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import yt_dlp
from dailywire_api.dw_api.client import ByNextPage, ByShowSeason, ByPodcastSeason, MiddlewareClient, DEFAULT_MIDDLEWARE_URL, MiddlewareAPIError
from dailywire_api.dw_api.movie import MovieMiddlewareClient
from source_contracts import (CollectionPage, DomainDescriptor, DownloadResult, EntrySnapshot,
                              MediaSnapshot, SourceError, SourceManifest, SourceMatch, SourceMediaReference, StreamLease,
                              SourceSearchItem, SourceSearchPage)
from source_contracts.network import install_public_network_guard, fetch_stream
from vodloft_source_media import download as acquire_media, UnsupportedRepresentation, lease_expiry

SOURCE_ID = "dailywire"

# The old WireLoft workflows retain their richer record shape while all of
# their upstream requests execute inside this independently installed Source.
_LEGACY_METHODS = frozenset({"get_show_page", "get_catalog", "get_square_show_thumbnails",
    "get_movie_playback", "get_movie_extra_playback", "get_user_info",
    "get_episodes_paginated", "get_episode_details", "get_show_id_by_slug",
    "get_season_id_by_slugs", "get_movie_page"})
_SELECTORS = {cls.__name__: cls for cls in (ByNextPage, ByShowSeason, ByPodcastSeason)}


def legacy_call(request: dict):
    """One allowlisted compatibility call; no caller-supplied endpoint or module."""
    method = request.get("method")
    if method not in _LEGACY_METHODS:
        raise ValueError("Unsupported Source operation")
    args, kwargs = request.get("args", []), request.get("kwargs", {})
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        raise ValueError("Invalid legacy request")
    if method == "get_episodes_paginated":
        selector = args[1] if len(args) > 1 else kwargs.get("selector")
        if not isinstance(selector, dict) or selector.get("type") not in _SELECTORS:
            raise ValueError("Invalid episode selector")
        selector_class = _SELECTORS[selector["type"]]
        value = selector_class(**selector.get("fields", {}))
        if len(args) > 1:
            args[1] = value
        else:
            kwargs["selector"] = value
    client = _client(request.get("access_token"), movie=method == "get_movie_page")
    result = getattr(client, method)(*args, **kwargs)
    if method == "get_episodes_paginated":
        return {"items": [item.model_dump(mode="json") for item in result.items],
            "next_page_url": result.next_page_url, "has_next": result.has_next}
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


def _client(token: str | None = None, movie: bool = False):
    klass = MovieMiddlewareClient if movie else MiddlewareClient
    return klass(access_token=token, base_url=DEFAULT_MIDDLEWARE_URL,
        pacing_settings=SimpleNamespace(min_fast_request_ms=100,
            min_slow_request_ms=120000, max_fast_requests=350),
        token_provider=lambda: token)


def _reference(kind: str, slug: str, upstream_id: str | None = None,
               sharing_url: str | None = None) -> SourceMediaReference:
    canonical = f"https://www.dailywire.com/{kind}/{slug}"
    return SourceMediaReference(source_id=SOURCE_ID, domain="dailywire.com", namespace=kind,
        # The provider replaces playback record IDs when an episode becomes
        # an archive. The verified content URL identifies that same edition.
        upstream_id=str(uuid.uuid5(uuid.NAMESPACE_URL, canonical)), url=canonical)


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
                                 episode_number=e.episode_number or None,
                                 capabilities={"download"} if getattr(e, "is_downloadable", True) else set())
                   for index, e in enumerate(record.latest_episodes[:max_entries], 1)]
        return MediaSnapshot(kind="collection", reference=_reference("show", record.slug, record.dw_id,
            record.sharing_url), title=record.title, description=record.description,
            artwork_url=record.thumbnail_portrait_path or record.background_image_path,
            entries=entries, enumeration_complete=False,
            capabilities={"enumerate_collection"})
    if kind in ("episode", "episodes"):
        record = client.get_episode_details(slug)
        return MediaSnapshot(kind="video", reference=_reference("episode", record.slug, record.dw_id,
            record.sharing_url), title=record.title, description=record.description,
            duration=record.duration, artwork_url=record.thumbnail_landscape_path,
            published_at=record.published_date, is_live=record.publish_status.casefold() == "live",
            formats=([{"code": "format_audio_only", "audio_only": True, "container": "mp3"}]
                if record.audio_url else []) + ([{"code": "format_1080p", "height": 1080}]
                if record.video_url else []),
            capabilities=({"download"} if record.is_downloadable else set()) |
                         ({"stream_lease"} if record.video_url else set()))
    movie = _client(token, movie=True)
    if kind in ("videos", "movies"):
        record = movie.get_movie_page(slug)
        extras = [EntrySnapshot(reference=_reference("clips", extra.slug,
            extra.dw_id or extra.slug, extra.sharing_url), title=extra.title,
            position=index, kind="movie_extra", extra_type=extra.movie_extra_type,
            capabilities={"download"})
            for index, extra in enumerate(record.movie_extras, 1)]
        return MediaSnapshot(kind="movie", reference=_reference("videos", record.slug, record.dw_id,
            record.sharing_url), title=record.title, description=record.description,
            duration=record.duration, artwork_url=record.thumbnail_portrait_path,
            extras=extras, formats=[{"code": "format_1080p", "height": 1080}],
            capabilities={"download", "stream_lease"})
    if kind in ("clips", "clip"):
        detail = movie.get_movie_extra_playback(slug)
        record = detail.metadata
        return MediaSnapshot(kind="movie_extra", reference=_reference("clips", record.slug,
            record.dw_id or record.slug, record.sharing_url), title=record.title,
            description=record.description, duration=record.duration,
            artwork_url=record.thumbnail_landscape_path,
            formats=[{"code": "format_1080p", "height": 1080}],
            capabilities={"download", "stream_lease"})
    raise ValueError("Unsupported Daily Wire media URL")


def _member_role(episode, season=None) -> str:
    trailer = getattr(episode, 'is_trailer', None) is True or bool(re.search(r'\bofficial\s+trailer\b', episode.title, re.I))
    raw = (episode.episode_number or '').split('.', 1)
    numbered = raw[0].isdigit()
    segment = int(raw[1]) if len(raw) == 2 and raw[1].isdigit() else 0
    if (season and season.slug == 'extras') or not numbered or segment >= 20:
        # Year-based podcast groups may identify full episodes by their date.
        if not numbered and season and season.name.isdigit() and len(season.name) == 4 and not trailer:
            return 'episode'
        return 'trailer' if trailer else 'auxiliary'
    if segment:
        return 'episode_extra'
    return 'trailer' if trailer else 'episode'


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
            role=_member_role(e),
            episode_number=e.episode_number or None,
            capabilities={"download"} if getattr(e, "is_downloadable", True) else set())
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
        role=_member_role(e, season),
        published_at=e.published_date, episode_number=e.episode_number or None,
        capabilities={"download"} if getattr(e, "is_downloadable", True) else set())
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


def search(query: str, cursor: str | None = None, limit: int = 30,
           token: str | None = None) -> SourceSearchPage:
    if (not query.strip() or len(query) > 200 or not 1 <= limit <= 50 or
        cursor is not None and (not cursor.isdecimal() or len(cursor) > 6)):
        raise ValueError("Invalid Source search")
    offset = int(cursor or "0")
    if offset > 10000:
        raise ValueError("Search result limit exceeded")
    catalog = _client(token).get_catalog()
    needle = query.casefold().strip()
    items = []
    for show in catalog.shows:
        if needle in f"{show.title} {show.author_name or ''}".casefold():
            items.append(SourceSearchItem(kind="collection", title=show.title,
                description=show.description, artwork_url=show.thumbnail_portrait_path,
                reference=_reference("show", show.slug, show.dw_id)))
    for movie in catalog.movies:
        if needle in f"{movie.title} {movie.author_name or ''}".casefold():
            items.append(SourceSearchItem(kind="movie", title=movie.title,
                description=movie.description, artwork_url=movie.thumbnail_portrait_path,
                reference=_reference("videos", movie.slug, movie.dw_id)))
    items.sort(key=lambda item: (item.title.casefold(), item.reference.upstream_id))
    page = items[offset:offset + limit]
    return SourceSearchPage(items=page,
        next_cursor=str(offset + limit) if offset + limit < len(items) else None)


def download(url: str, staging: str, preferred_format: str = "format_1080p",
             token: str | None = None, representation: dict | None = None,
             metadata: dict | None = None, reference: dict | None = None) -> DownloadResult:
    snapshot = resolve(url, token=token)
    expected = SourceMediaReference.model_validate(reference) if reference else None
    if expected and any(getattr(expected, field) != getattr(snapshot.reference, field)
                        for field in ("source_id", "domain", "namespace", "upstream_id")):
        raise ValueError("The Source URL now identifies different media")
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
    return acquire_media(playback_url, staging, preferred_format, representation,
        metadata or {"title": snapshot.title, "description": snapshot.description or ""})


def stream_lease(url: str, token: str | None = None) -> StreamLease:
    parsed = urlsplit(url)
    parts = parsed.path.strip("/").split("/")
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in
        {"dailywire.com", "www.dailywire.com"} or len(parts) != 2 or
        not re.fullmatch(r"[a-zA-Z0-9_-]+", parts[1])):
        raise ValueError("Invalid Daily Wire playback reference")
    kind, slug = parts
    if kind in ("episode", "episodes"):
        playback_url = _client(token).get_episode_details(slug).video_url
    elif kind in ("clips", "clip"):
        playback_url = _client(token, movie=True).get_movie_extra_playback(slug).video_url
    elif kind in ("videos", "movies"):
        playback_url = _client(token, movie=True).get_movie_playback(slug).video_url
    else:
        raise ValueError("Only playable media supports leases")
    if not playback_url or urlsplit(playback_url).scheme != "https":
        raise ValueError("No playable representation is available")
    return StreamLease(transport="hls" if urlsplit(playback_url).path.endswith(".m3u8") else "http",
        url=playback_url, renewable=True, seekable=True, expires_at=lease_expiry(playback_url),
        representation_id=hashlib.sha256(urlsplit(playback_url).path.encode()).hexdigest())


def main():
    request = json.load(sys.stdin)
    operation = request["operation"]
    if operation in ("resolve", "download", "entries", "search", "legacy_call", "stream_lease", "stream_fetch",
                     "auth_start", "auth_poll", "auth_refresh"):
        install_public_network_guard()
    if operation == "manifest":
        result = SourceManifest(source_id=SOURCE_ID, display_name="Daily Wire API",
            version="1.0.0", upstream_versions={"dailywire-api": "0.2.1", "yt-dlp": yt_dlp.version.__version__},
            native_helpers=["ffmpeg"], capabilities={"health", "resolve_url", "enumerate_collection", "enumerate_pages", "download", "domain_catalogue", "search", "stream_lease", "authentication"},
            exhaustive_domain_catalogue=True,
            configuration_schema=[{"name": "access_token", "label": "Access token", "kind": "secret",
                                   "required": False}])
    elif operation == "health":
        result = {"healthy": bool(shutil.which("ffmpeg")), "protocol_version": 1}
        if result["healthy"]:
            subprocess.run(["ffmpeg", "-version"], timeout=10, check=True, capture_output=True)
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
    elif operation == "search":
        result = search(request["query"], request.get("cursor"), request.get("limit", 30),
                        request.get("access_token"))
    elif operation == "download":
        result = download(request["url"], request["staging"], request.get("preferred_format", "format_1080p"),
                          request.get("access_token"), request.get("representation"), request.get("metadata"), request.get("reference"))
    elif operation == "legacy_call":
        result = legacy_call(request)
    elif operation == "stream_lease":
        result = stream_lease(request["url"], request.get("access_token"))
    elif operation == "stream_fetch":
        result = fetch_stream(request["url"], request.get("headers"), request.get("byte_range"))
    elif operation in ("auth_start", "auth_poll", "auth_refresh"):
        from . import auth
        result = (auth.start() if operation == "auth_start" else
            auth.poll(request["private_state"]) if operation == "auth_poll" else
            auth.refresh(request["private_state"]))
    else:
        print(json.dumps({"error": SourceError(code="unsupported_operation", message="This Source does not support the requested operation").model_dump()}))
        return
    print(result.model_dump_json(exclude_unset=True) if hasattr(result, "model_dump_json") else json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if isinstance(exc, MiddlewareAPIError):
            code, message = (
                ("authentication_required", "Daily Wire authorization is required")
                if exc.status_code in (401, 403) else
                ("rate_limited", "Daily Wire is rate limited")
                if exc.status_code == 429 else ("unavailable", "Daily Wire operation failed"))
        elif isinstance(exc, HTTPError) and exc.code in (401, 403, 429):
            code = "rate_limited" if exc.code == 429 else "authentication_required"
            message = "Daily Wire is rate limited" if code == "rate_limited" else "Daily Wire authorization is required"
        elif isinstance(exc, PermissionError):
            code, message = "authentication_required", "Daily Wire authorization is required"
        elif isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
            code, message = "insufficient_disk", "Insufficient staging disk space"
        elif isinstance(exc, UnsupportedRepresentation):
            code, message = "unsupported_format", "The requested representation is unavailable"
        elif isinstance(exc, ValueError):
            code = "unsupported_operation" if str(exc).startswith("Unsupported Source operation") else "invalid_url"
            message = "Source operation is unsupported" if code == "unsupported_operation" else "Daily Wire media reference is invalid"
        else:
            code, message = "unavailable", "Daily Wire operation failed"
        print(json.dumps({"error": SourceError(code=code, message=message).model_dump()}))
