"""NPO Start Source worker: API-first metadata, crawler fallback and account playback."""

from __future__ import annotations

import errno
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from source_contracts import (
    CollectionPage, DomainDescriptor, DownloadResult, EntrySnapshot, FormatDescriptor,
    MediaSnapshot, RepresentationPolicy, SourceError, SourceManifest, SourceMatch,
    SourceMediaReference, SourceSearchItem, SourceSearchPage, StreamLease,
)
from source_contracts.network import fetch_stream, install_public_network_guard

from . import crawler
from .client import (
    ApiUnavailable, AuthenticationRequired, DRMProtected, MediaUnavailable,
    NPOClient, Playback, RateLimited,
)

SOURCE_ID = "npo"
_DOMAINS = {"npo.nl", "www.npo.nl"}
_PLAYABLE_CAPABILITIES = {"download", "stream_lease"}


class UnsupportedRepresentation(ValueError):
    pass


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or
            (parsed.hostname or "").lower() not in _DOMAINS or
            parsed.username is not None or parsed.password is not None):
        raise ValueError("Enter a public NPO media URL")
    return parsed._replace(scheme="https", netloc="npo.nl", fragment="").geturl()


def _parts(url: str) -> list[str]:
    return [part for part in urlsplit(_canonical_url(url)).path.split("/") if part]


def _series_slug(url: str) -> str:
    parts = _parts(url)
    try:
        index = parts.index("serie")
        slug = parts[index + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError("NPO series URL is invalid") from exc
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", slug):
        raise ValueError("NPO series slug is invalid")
    return slug


def _program_slug(url: str) -> str:
    parts = _parts(url)
    if parts and parts[-1] == "afspelen":
        parts.pop()
    ignored = {"start", "serie", "video", "afspelen"}
    slug = next((part for part in reversed(parts) if part not in ignored), "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", slug):
        raise ValueError("NPO program slug is invalid")
    return slug


def _is_collection_url(url: str) -> bool:
    parts = _parts(url)
    if len(parts) < 3 or parts[:2] != ["start", "serie"]:
        return False
    return len(parts) == 3 or (len(parts) == 4 and parts[3] in {"afleveringen", "fragmenten"})


def _client(email: str | None = None, password: str | None = None) -> NPOClient:
    return NPOClient(email, password)


def _items(value) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("items", "results", "programs", "seasons"):
        found = value.get(key)
        if isinstance(found, list):
            return [item for item in found if isinstance(item, dict)]
    data = value.get("data")
    if isinstance(data, (dict, list)):
        nested = _items(data)
        if nested:
            return nested
    return []


def _record(value, *, playable: bool = False) -> dict | None:
    if not isinstance(value, dict):
        return None
    required = "productId" if playable else None
    if (required and value.get(required)) or (
            not required and any(value.get(key) for key in ("guid", "slug", "title"))):
        return value
    for key in ("data", "item", "program", "series"):
        candidate = value.get(key)
        if isinstance(candidate, dict):
            found = _record(candidate, playable=playable)
            if found:
                return found
    return None


def _description(value) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        for key in ("long", "short", "description", "synopsis"):
            found = value.get(key)
            if isinstance(found, str) and found:
                return found
    return None


def _image(record: dict) -> str | None:
    images = record.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, dict) and isinstance(image.get("url"), str):
                return image["url"]
    for key in ("image", "imageUrl", "thumbnail", "_crawler_image"):
        value = record.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None


def _published(record: dict) -> datetime | None:
    value = record.get("firstBroadcastDate") or record.get("publishedAt") or record.get("date")
    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 10_000_000_000:
            stamp /= 1000
        try:
            return datetime.fromtimestamp(stamp, timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _program_url(record: dict, fallback: str | None = None) -> str:
    crawler_url = record.get("_crawler_url")
    if isinstance(crawler_url, str):
        return _canonical_url(crawler_url)
    slug = record.get("slug")
    series = record.get("series") if isinstance(record.get("series"), dict) else {}
    season = record.get("season") if isinstance(record.get("season"), dict) else {}
    if all(isinstance(value, str) and value for value in
           (series.get("slug"), season.get("slug"), slug)):
        return (
            f"https://npo.nl/start/serie/{series['slug']}/{season['slug']}/{slug}/afspelen"
        )
    if isinstance(slug, str) and slug:
        return f"https://npo.nl/start/video/{slug}"
    if fallback:
        return _canonical_url(fallback)
    raise ValueError("NPO program has no usable URL")


def _program_reference(record: dict, fallback_url: str | None = None) -> SourceMediaReference:
    product_id = record.get("productId")
    identity = product_id or record.get("guid") or record.get("slug")
    if not isinstance(identity, str) or not identity:
        raise ValueError("NPO program has no stable identity")
    return SourceMediaReference(
        source_id=SOURCE_ID,
        domain="npo.nl",
        namespace="program",
        upstream_id=identity,
        url=_program_url(record, fallback_url),
    )


def _series_reference(record: dict, slug: str) -> SourceMediaReference:
    identity = record.get("guid") or slug
    return SourceMediaReference(
        source_id=SOURCE_ID,
        domain="npo.nl",
        namespace="series",
        upstream_id=str(identity),
        url=f"https://npo.nl/start/serie/{slug}",
    )


def _program_entry(record: dict, position: int) -> EntrySnapshot:
    season = record.get("season") if isinstance(record.get("season"), dict) else {}
    group = season.get("seasonKey") or season.get("label") or record.get("seasonKey")
    episode_number = record.get("programKey") or record.get("episodeNumber")
    return EntrySnapshot(
        reference=_program_reference(record),
        title=str(record.get("title") or record.get("mainTitle") or "NPO program"),
        position=position,
        kind="video",
        group=str(group) if group is not None else None,
        episode_number=str(episode_number) if episode_number is not None else None,
        published_at=_published(record),
        capabilities=set(_PLAYABLE_CAPABILITIES) if record.get("productId") else None,
    )


def _sort_programs(programs: list[dict]) -> list[dict]:
    unique: dict[str, dict] = {}
    for program in programs:
        identity = program.get("productId") or program.get("guid") or program.get("slug")
        if identity:
            unique.setdefault(str(identity), program)
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(unique.values(), key=lambda item: (
        _published(item) or minimum,
        str((item.get("season") or {}).get("seasonKey")
            if isinstance(item.get("season"), dict) else item.get("seasonKey") or ""),
        str(item.get("programKey") or item.get("episodeNumber") or ""),
        str(item.get("title") or ""),
    ))


def _series_data(url: str, client: NPOClient) -> tuple[dict, list[dict], bool]:
    slug = _series_slug(url)
    try:
        detail = _record(client.series_detail(slug))
        if detail is None:
            raise ApiUnavailable("NPO series detail has an unknown shape")
        programs: list[dict] = []
        series_type = detail.get("type")
        if isinstance(series_type, str) and series_type.endswith("series"):
            seasons = _items(client.series_seasons(slug, series_type))
            for season in seasons:
                guid = season.get("guid")
                if isinstance(guid, str) and guid:
                    season_programs = _items(client.programs_by_season(guid))
                    for program in season_programs:
                        if not isinstance(program.get("season"), dict):
                            program = {**program, "season": season}
                        programs.append(program)
        guid = detail.get("guid")
        if not programs and isinstance(guid, str) and guid:
            programs.extend(_items(client.programs_by_series(guid)))
        if not programs:
            # An empty result can be legitimate, but crawling it gives us a
            # chance to recover when an undocumented API shape changed.
            crawled_detail, crawled_programs = crawler.series(url, client)
            if crawled_programs:
                return {**detail, **crawled_detail}, _sort_programs(crawled_programs), False
        return detail, _sort_programs(programs), True
    except (ApiUnavailable, MediaUnavailable):
        detail, programs = crawler.series(url, client)
        return detail, _sort_programs(programs), False


def _playable_data(url: str, client: NPOClient) -> tuple[dict, bool]:
    slug = _program_slug(url)
    try:
        detail = _record(client.program_detail(slug), playable=True)
        if detail is None:
            raise ApiUnavailable("NPO program detail has an unknown shape")
        return detail, True
    except (ApiUnavailable, MediaUnavailable):
        return crawler.program(url, client), False


def _program_snapshot(record: dict, fallback_url: str) -> MediaSnapshot:
    title = record.get("title") or record.get("mainTitle") or record.get("_crawler_title")
    if not isinstance(title, str) or not title:
        title = _program_slug(fallback_url).replace("-", " ").title()
    synopsis = _description(record.get("synopsis")) or _description(record.get("description"))
    if not synopsis:
        synopsis = _description(record.get("_crawler_description"))
    duration = record.get("durationInSeconds") or record.get("duration")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        duration = None
    restriction = record.get("restrictions")
    subscription = None
    if isinstance(restriction, list):
        for item in restriction:
            if isinstance(item, dict) and item.get("subscriptionType"):
                subscription = item["subscriptionType"]
                if subscription == "premium":
                    break
    series = record.get("series") if isinstance(record.get("series"), dict) else {}
    return MediaSnapshot(
        kind="video",
        reference=_program_reference(record, fallback_url),
        title=title,
        description=synopsis,
        duration=float(duration) if duration is not None else None,
        published_at=_published(record),
        capabilities=set(_PLAYABLE_CAPABILITIES),
        artwork_url=_image(record),
        author=series.get("title") if isinstance(series.get("title"), str) else None,
        formats=[
            FormatDescriptor(code="format_720p", container="mp4", height=720),
            FormatDescriptor(code="format_1080p", container="mp4", height=1080),
            FormatDescriptor(code="format_audio_only", container="m4a", audio_only=True),
        ],
        extensions={"npo": {
            "guid": record.get("guid"),
            "subscription": subscription,
        }},
    )


def resolve(url: str, max_entries: int = 100, email: str | None = None,
            password: str | None = None) -> MediaSnapshot:
    url = _canonical_url(url)
    if not 1 <= max_entries <= 500:
        raise ValueError("Choose between one and 500 preview entries")
    client = _client(email, password)
    if _is_collection_url(url):
        detail, programs, _ = _series_data(url, client)
        slug = _series_slug(url)
        title = detail.get("title") or slug.replace("-", " ").title()
        synopsis = _description(detail.get("synopsis")) or _description(detail.get("description"))
        entries = [_program_entry(program, index) for index, program in
                   enumerate(programs[:max_entries], 1)]
        return MediaSnapshot(
            kind="collection",
            reference=_series_reference(detail, slug),
            title=str(title),
            description=synopsis,
            artwork_url=_image(detail),
            entries=entries,
            enumeration_complete=len(programs) <= max_entries,
            extensions={"npo": {"series_type": detail.get("type")}},
        )
    record, _ = _playable_data(url, client)
    return _program_snapshot(record, url)


def entries(url: str, cursor: str | None = None, limit: int = 50,
            email: str | None = None, password: str | None = None) -> CollectionPage:
    if not 1 <= limit <= 100:
        raise ValueError("Choose between one and 100 Collection entries")
    if cursor is not None and (not cursor.isdecimal() or len(cursor) > 8):
        raise ValueError("Invalid NPO Collection cursor")
    offset = int(cursor or "0")
    _, programs, _ = _series_data(_canonical_url(url), _client(email, password))
    page = programs[offset:offset + limit]
    snapshots = [_program_entry(program, offset + index) for index, program in enumerate(page, 1)]
    next_offset = offset + len(page)
    complete = next_offset >= len(programs)
    return CollectionPage(
        entries=snapshots,
        next_cursor=None if complete else str(next_offset),
        complete=complete,
    )


def _search_item(record: dict) -> SourceSearchItem | None:
    if record.get("productId"):
        try:
            reference = _program_reference(record)
        except ValueError:
            return None
        return SourceSearchItem(
            reference=reference,
            kind="video",
            title=str(record.get("title") or record.get("mainTitle") or "NPO program"),
            description=_description(record.get("synopsis")),
            artwork_url=_image(record),
        )
    slug = record.get("slug")
    if not isinstance(slug, str) or not slug:
        return None
    try:
        reference = _series_reference(record, slug)
    except ValueError:
        return None
    return SourceSearchItem(
        reference=reference,
        kind="collection",
        title=str(record.get("title") or slug.replace("-", " ").title()),
        description=_description(record.get("synopsis")),
        artwork_url=_image(record),
    )


def search(query: str, cursor: str | None = None, limit: int = 30,
           email: str | None = None, password: str | None = None) -> SourceSearchPage:
    if not query.strip() or len(query) > 200 or not 1 <= limit <= 50:
        raise ValueError("Invalid NPO search")
    if cursor is not None and (not cursor.isdecimal() or len(cursor) > 6):
        raise ValueError("Invalid NPO search cursor")
    offset = int(cursor or "0")
    client = _client(email, password)
    try:
        records = _items(client.search(query, "series")) + _items(client.search(query, "broadcasts"))
    except (ApiUnavailable, MediaUnavailable):
        records = crawler.search(query, client, limit=max(50, offset + limit))
    normalized = [item for item in (_search_item(record) for record in records) if item]
    deduplicated: dict[tuple[str, str], SourceSearchItem] = {}
    for item in normalized:
        key = (item.reference.namespace, item.reference.upstream_id)
        deduplicated.setdefault(key, item)
    values = sorted(deduplicated.values(), key=lambda item: (item.title.casefold(), item.reference.upstream_id))
    page = values[offset:offset + limit]
    return SourceSearchPage(
        items=page,
        next_cursor=str(offset + limit) if offset + limit < len(values) else None,
    )


def _emit_progress(percent: float) -> None:
    packet = {"event": {"stage": "downloading", "percent": max(0, min(100, percent))}}
    print(json.dumps(packet, separators=(",", ":")), file=sys.stderr, flush=True)


def _ffmpeg_headers(headers: dict[str, str]) -> str:
    safe = []
    for key, value in headers.items():
        if (not re.fullmatch(r"[A-Za-z0-9-]{1,64}", key) or
                not isinstance(value, str) or len(value) > 4096 or
                "\r" in value or "\n" in value):
            raise ValueError("NPO playback returned an invalid HTTP header")
        safe.append(f"{key}: {value}\r\n")
    return "".join(safe)


def _acquire(playback: Playback, staging: str, preferred_format: str,
             duration: float | None, representation: dict | None,
             metadata: dict | None) -> DownloadResult:
    policy = RepresentationPolicy.model_validate(representation or {})
    if policy.artwork:
        raise UnsupportedRepresentation("NPO Source does not embed artwork during acquisition")
    destination = Path(staging).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    audio_only = preferred_format == "format_audio_only"
    if audio_only:
        container = policy.container if policy.container in {"m4a", "mp3", "opus"} else "m4a"
        codec = {"m4a": "aac", "mp3": "libmp3lame", "opus": "libopus"}[container]
        if policy.audio_codec not in {"source", "aac" if container == "m4a" else container}:
            raise UnsupportedRepresentation("The requested NPO audio codec is unsupported")
        output = destination / f"media.{container}"
    else:
        if preferred_format not in {"format_720p", "format_1080p", "format_4k"}:
            raise UnsupportedRepresentation("The requested NPO video format is unsupported")
        if policy.container not in {"source", "mp4", "mkv"}:
            raise UnsupportedRepresentation("The requested container is unsupported for NPO video")
        if policy.video_codec not in {"source", "h264"} or policy.audio_codec not in {"source", "aac"}:
            raise UnsupportedRepresentation("The requested NPO codecs are unsupported")
        container = "mkv" if policy.container == "mkv" else "mp4"
        output = destination / f"media.{container}"

    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-headers", _ffmpeg_headers(playback.headers),
        "-i", playback.url,
    ]
    if audio_only:
        command += ["-map", "0:a:0?", "-vn", "-c:a", codec]
        if codec == "aac":
            command += ["-b:a", "192k"]
    else:
        height = {"format_720p": 720, "format_1080p": 1080, "format_4k": 2160}[preferred_format]
        command += [
            "-map", "0:v:0?", "-map", "0:a:0?",
            "-vf", f"scale=-2:min({height}\\,ih)",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
        ]
        if policy.subtitles:
            command += ["-map", "0:s?", "-c:s", "copy" if container == "mkv" else "mov_text"]
        command += ["-map_chapters", "0"]
    if policy.embed_metadata and metadata:
        for key in ("title", "description", "series", "episode"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                command += ["-metadata", f"{key}={value[:4000]}"]
    command += ["-progress", "pipe:1", "-nostats", str(output)]

    _emit_progress(0)
    # Discard FFmpeg stderr so signed upstream URLs can never be reflected into
    # Source diagnostics and so an error stream cannot back-pressure the worker.
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, bufsize=1)
    last = 0
    assert process.stdout is not None
    for line in process.stdout:
        key, _, value = line.strip().partition("=")
        if key not in {"out_time_us", "out_time_ms"} or not duration:
            continue
        try:
            elapsed = int(value) / 1_000_000
        except ValueError:
            continue
        percent = min(99, int(elapsed / duration * 100))
        if percent >= last + 2:
            last = percent
            _emit_progress(percent)
    returncode = process.wait()
    if returncode != 0:
        # Never return FFmpeg diagnostics: signed stream URLs can occur there.
        raise RuntimeError(f"NPO media acquisition failed with exit status {returncode}")
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError("NPO media acquisition produced no output")
    _emit_progress(100)
    return DownloadResult(filename=output.name, size=output.stat().st_size)


def _expected_reference(snapshot: MediaSnapshot, reference: dict | None) -> None:
    if not reference:
        return
    expected = SourceMediaReference.model_validate(reference)
    actual = snapshot.reference
    if any(getattr(expected, field) != getattr(actual, field)
           for field in ("source_id", "domain", "namespace", "upstream_id")):
        raise ValueError("The NPO URL now identifies different media")


def download(url: str, staging: str, preferred_format: str = "format_1080p",
             email: str | None = None, password: str | None = None,
             representation: dict | None = None, metadata: dict | None = None,
             reference: dict | None = None) -> DownloadResult:
    snapshot = resolve(url, email=email, password=password)
    _expected_reference(snapshot, reference)
    if snapshot.kind == "collection" or snapshot.reference.namespace != "program":
        raise ValueError("Download one NPO program, not a Collection")
    product_id = snapshot.reference.upstream_id
    playback = _client(email, password).playback(product_id, snapshot.reference.url)
    return _acquire(playback, staging, preferred_format, snapshot.duration,
                    representation, metadata or {
                        "title": snapshot.title,
                        "description": snapshot.description or "",
                    })


def stream_lease(url: str, email: str | None = None,
                 password: str | None = None) -> StreamLease:
    snapshot = resolve(url, email=email, password=password)
    if snapshot.kind == "collection" or snapshot.reference.namespace != "program":
        raise ValueError("Only one NPO program can be streamed")
    playback = _client(email, password).playback(
        snapshot.reference.upstream_id, snapshot.reference.url)
    return StreamLease(
        transport=playback.transport,
        url=playback.url,
        renewable=True,
        seekable=True,
        headers=playback.headers,
        representation_id=snapshot.reference.upstream_id,
    )


def _source_error(exc: Exception) -> SourceError:
    if isinstance(exc, AuthenticationRequired):
        return SourceError(code="authentication_required",
                           message="NPO account authentication is required")
    if isinstance(exc, RateLimited):
        return SourceError(code="rate_limited", message="NPO rate limit reached")
    if isinstance(exc, (DRMProtected, UnsupportedRepresentation)):
        return SourceError(code="unsupported_format",
                           message="NPO playback uses an unsupported media representation")
    if isinstance(exc, MediaUnavailable):
        return SourceError(code="unavailable", message="NPO media is currently unavailable")
    if isinstance(exc, (ApiUnavailable, crawler.CrawlError)):
        return SourceError(code="runtime_error", message="NPO Source could not interpret the site")
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return SourceError(code="insufficient_disk", message="Insufficient staging disk space")
    if isinstance(exc, ValueError):
        code = "unsupported_operation" if str(exc).startswith("Unsupported Source operation") else "invalid_url"
        return SourceError(code=code, message=(
            "Source operation is unsupported" if code == "unsupported_operation"
            else "NPO media reference is invalid"))
    return SourceError(code="runtime_error", message="NPO Source operation failed")


def main() -> None:
    request = json.load(sys.stdin)
    operation = request["operation"]
    if operation in {"resolve", "entries", "search", "download", "stream_lease", "stream_fetch"}:
        install_public_network_guard()

    email, password = request.get("email"), request.get("password")
    if operation == "manifest":
        result = SourceManifest(
            source_id=SOURCE_ID,
            display_name="NPO Start",
            version="1.0.0",
            native_helpers=["ffmpeg"],
            capabilities={
                "health", "resolve_url", "enumerate_collection", "enumerate_pages",
                "download", "domain_catalogue", "search", "stream_lease",
            },
            exhaustive_domain_catalogue=True,
            configuration_schema=[
                {"name": "email", "label": "NPO account email", "kind": "text", "required": True},
                {"name": "password", "label": "NPO account password", "kind": "secret", "required": True},
            ],
            catalogue_revision="1",
        )
    elif operation == "health":
        result = {"healthy": bool(shutil.which("ffmpeg")), "protocol_version": 1}
        if result["healthy"]:
            subprocess.run(["ffmpeg", "-version"], timeout=10, check=True,
                           capture_output=True)
    elif operation == "domains":
        result = {
            "items": [DomainDescriptor(
                hostname="npo.nl",
                display_name="NPO",
                source_id=SOURCE_ID,
                aliases=["www.npo.nl"],
            ).model_dump()],
            "next_cursor": None,
            "exhaustive": True,
            "supports_url_resolution_outside_catalog": False,
            "catalog_revision": "1",
        }
    elif operation == "match":
        try:
            parts = _parts(request["url"])
            supported = len(parts) >= 2 and parts[0] == "start" and (
                parts[1] in {"serie", "video", "afspelen"})
        except ValueError:
            supported = False
        result = SourceMatch(
            source_id=SOURCE_ID,
            confidence=100 if supported else 0,
            reason="NPO Start media URL" if supported else "Not an NPO Start media URL",
        )
    elif operation == "resolve":
        result = resolve(request["url"], request.get("max_entries", 100), email, password)
    elif operation == "entries":
        result = entries(request["url"], request.get("cursor"), request.get("limit", 50),
                         email, password)
    elif operation == "search":
        result = search(request["query"], request.get("cursor"), request.get("limit", 30),
                        email, password)
    elif operation == "download":
        result = download(
            request["url"], request["staging"],
            request.get("preferred_format", "format_1080p"),
            email, password, request.get("representation"), request.get("metadata"),
            request.get("reference"),
        )
    elif operation == "stream_lease":
        result = stream_lease(request["url"], email, password)
    elif operation == "stream_fetch":
        result = fetch_stream(request["url"], request.get("headers"),
                              request.get("byte_range"))
    else:
        raise ValueError("Unsupported Source operation")

    print(result.model_dump_json(exclude_unset=True)
          if hasattr(result, "model_dump_json") else json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": _source_error(exc).model_dump()}))
