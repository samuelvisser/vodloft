"""Pinchflat's database, read from a private copy.

Pinchflat keeps everything in one SQLite file, with recent changes in its
``-wal`` file while it runs. The reader copies both before opening them, so the
original is never touched, and refuses a copy that SQLite finds damaged or a
database newer than the versions it knows.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NEWEST_KNOWN_VERSION = 20250317213740
"""The newest Pinchflat migration this reader knows (Pinchflat at 67d8bd5, December 2025)."""

_REQUIRED_COLUMNS = {
    "sources": {"id", "collection_name", "collection_type", "original_url", "media_profile_id"},
    "media_profiles": {"id", "name", "output_path_template"},
    "media_items": {"id", "media_id", "source_id", "media_filepath"},
}


class PinchflatReadError(ValueError):
    """The upload is not a Pinchflat database this VODLoft can read."""


@dataclass(frozen=True)
class PinchflatProfile:
    id: int
    name: str
    output_path_template: str
    preferred_resolution: str | None = None
    download_subs: bool = False
    download_auto_subs: bool = False
    embed_subs: bool = False
    sub_langs: str | None = None
    download_thumbnail: bool = False
    embed_thumbnail: bool = False
    download_metadata: bool = False
    embed_metadata: bool = False
    download_nfo: bool = False
    download_source_images: bool = False
    shorts_behaviour: str = "include"
    livestream_behaviour: str = "include"
    sponsorblock_behaviour: str | None = None
    sponsorblock_categories: tuple[str, ...] = ()
    redownload_delay_days: int | None = None
    media_container: str | None = None
    audio_track: str | None = None
    marked_for_deletion: bool = False


@dataclass(frozen=True)
class PinchflatSource:
    id: int
    collection_type: str
    collection_name: str | None
    collection_id: str | None
    original_url: str
    media_profile_id: int
    custom_name: str | None = None
    enabled: bool = True
    download_media: bool = True
    download_cutoff_date: str | None = None
    retention_period_days: int | None = None
    output_path_template_override: str | None = None
    title_filter_regex: str | None = None
    min_duration_seconds: int | None = None
    max_duration_seconds: int | None = None
    cookie_behaviour: str | None = None
    index_frequency_minutes: int | None = None
    """How often Pinchflat lists the source; -1 is never."""
    fast_index: bool = False
    """Whether Pinchflat looks for new videos every few minutes, which overrides the index frequency."""
    series_directory: str | None = None
    nfo_filepath: str | None = None
    poster_filepath: str | None = None
    fanart_filepath: str | None = None
    banner_filepath: str | None = None
    marked_for_deletion: bool = False
    added_at: datetime | None = None
    """When the source was added to Pinchflat."""

    @property
    def name(self) -> str:
        return self.custom_name or self.collection_name or self.original_url


@dataclass(frozen=True)
class PinchflatItem:
    id: int
    source_id: int
    media_id: str
    title: str | None = None
    media_filepath: str | None = None
    uploaded_at: str | None = None
    playlist_index: int | None = None
    upload_date_index: int | None = None
    prevent_download: bool = False
    prevent_culling: bool = False
    culled_at: str | None = None
    livestream: bool = False
    short_form_content: bool = False
    subtitle_filepaths: tuple[tuple[str, str], ...] = ()
    thumbnail_filepath: str | None = None
    metadata_filepath: str | None = None
    nfo_filepath: str | None = None


@dataclass(frozen=True)
class PinchflatSettings:
    restrict_filenames: bool = False
    extractor_sleep_interval_seconds: float | None = None
    download_throughput_limit: str | None = None
    youtube_api_key: str | None = None
    apprise_server: str | None = None
    """Pinchflat's Apprise URLs, which hold sign-ins."""
    yt_dlp_version: str | None = None


@dataclass(frozen=True)
class PinchflatData:
    version: int
    profiles: tuple[PinchflatProfile, ...]
    sources: tuple[PinchflatSource, ...]
    items: tuple[PinchflatItem, ...]
    settings: PinchflatSettings
    metadata_files: dict[int, str] = field(default_factory=dict)
    """The yt-dlp metadata Pinchflat saved for a media item, by item id, as Pinchflat's path."""


def private_copy(database: Path, directory: Path) -> Path:
    """Copy ``database`` and its ``-wal`` file into ``directory``; the copy is what the reader opens."""
    directory.mkdir(parents=True, exist_ok=True)
    copy = directory / "pinchflat.db"
    for suffix in ("", "-wal", "-shm"):
        (directory / f"pinchflat.db{suffix}").unlink(missing_ok=True)
    shutil.copyfile(database, copy)
    wal = database.with_name(database.name + "-wal")
    if wal.is_file() and wal.stat().st_size > 0:
        shutil.copyfile(wal, directory / "pinchflat.db-wal")
    return copy


def _connect(copy: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(copy)
        connection.row_factory = sqlite3.Row
        result = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise PinchflatReadError(f"This is not a database SQLite can open: {exc}") from exc
    if result is None or result[0] != "ok":
        connection.close()
        raise PinchflatReadError(
            "The database copy is damaged, which happens when Pinchflat writes while it is copied. "
            "Pause Pinchflat and upload it again."
        )
    return connection


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info('{table}')")}


def check_version(connection: sqlite3.Connection) -> int:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "schema_migrations" not in tables or not set(_REQUIRED_COLUMNS) <= tables:
        raise PinchflatReadError("This is not a Pinchflat database")
    version = connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
    if version is None:
        raise PinchflatReadError("This Pinchflat database has no version")
    version = int(version)
    if version > NEWEST_KNOWN_VERSION:
        raise PinchflatReadError(
            f"This Pinchflat database is version {version}, newer than this VODLoft knows ({NEWEST_KNOWN_VERSION}). "
            "Update VODLoft, or tell its developers which Pinchflat release you run."
        )
    for table, required in _REQUIRED_COLUMNS.items():
        missing = required - _columns(connection, table)
        if missing:
            raise PinchflatReadError(
                f"Pinchflat's {table} table has no {', '.join(sorted(missing))}. "
                "Update Pinchflat first, then upload its database again."
            )
    return version


def _rows(connection: sqlite3.Connection, table: str, order: str = "id") -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order}")]


def _bool(value: object) -> bool:
    return bool(value) and value not in ("0", "false")


def _timestamp(value: object) -> datetime | None:
    """One of Pinchflat's timestamps, which it writes in UTC, such as ``2025-03-03T11:05:53Z``."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def _int(value: object) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _list(value: object) -> tuple[str, ...]:
    if not value:
        return ()
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return tuple(part.strip() for part in str(value).split(",") if part.strip())
    return tuple(str(part) for part in parsed) if isinstance(parsed, list) else ()


def _subtitles(value: object) -> tuple[tuple[str, str], ...]:
    # Ecto stores [["en", "/downloads/….en.srt"], …], each pair JSON-encoded once more.
    found: list[tuple[str, str]] = []
    for entry in _list(value):
        try:
            pair = json.loads(entry)
        except ValueError:
            continue
        if isinstance(pair, list) and len(pair) == 2 and all(isinstance(part, str) for part in pair):
            found.append((pair[0], pair[1]))
    return tuple(found)


def _profile(row: dict[str, Any]) -> PinchflatProfile:
    return PinchflatProfile(
        id=row["id"], name=row.get("name") or f"Media profile {row['id']}",
        output_path_template=row.get("output_path_template") or "",
        preferred_resolution=row.get("preferred_resolution"),
        download_subs=_bool(row.get("download_subs")), download_auto_subs=_bool(row.get("download_auto_subs")),
        embed_subs=_bool(row.get("embed_subs")), sub_langs=row.get("sub_langs"),
        download_thumbnail=_bool(row.get("download_thumbnail")), embed_thumbnail=_bool(row.get("embed_thumbnail")),
        download_metadata=_bool(row.get("download_metadata")), embed_metadata=_bool(row.get("embed_metadata")),
        download_nfo=_bool(row.get("download_nfo")), download_source_images=_bool(row.get("download_source_images")),
        shorts_behaviour=row.get("shorts_behaviour") or "include",
        livestream_behaviour=row.get("livestream_behaviour") or "include",
        sponsorblock_behaviour=row.get("sponsorblock_behaviour"),
        sponsorblock_categories=_list(row.get("sponsorblock_categories")),
        redownload_delay_days=_int(row.get("redownload_delay_days")),
        media_container=row.get("media_container"), audio_track=row.get("audio_track"),
        marked_for_deletion=row.get("marked_for_deletion_at") is not None,
    )


def _source(row: dict[str, Any]) -> PinchflatSource:
    return PinchflatSource(
        id=row["id"], collection_type=row.get("collection_type") or "channel",
        collection_name=row.get("collection_name"), collection_id=row.get("collection_id"),
        original_url=row["original_url"], media_profile_id=row["media_profile_id"],
        custom_name=row.get("custom_name"),
        enabled=_bool(row.get("enabled", 1)), download_media=_bool(row.get("download_media", 1)),
        download_cutoff_date=row.get("download_cutoff_date"),
        retention_period_days=_int(row.get("retention_period_days")),
        output_path_template_override=row.get("output_path_template_override") or None,
        title_filter_regex=row.get("title_filter_regex") or None,
        min_duration_seconds=_int(row.get("min_duration_seconds")),
        max_duration_seconds=_int(row.get("max_duration_seconds")),
        cookie_behaviour=row.get("cookie_behaviour"),
        index_frequency_minutes=_int(row.get("index_frequency_minutes")),
        fast_index=_bool(row.get("fast_index")),
        series_directory=row.get("series_directory"), nfo_filepath=row.get("nfo_filepath"),
        poster_filepath=row.get("poster_filepath"), fanart_filepath=row.get("fanart_filepath"),
        banner_filepath=row.get("banner_filepath"),
        marked_for_deletion=row.get("marked_for_deletion_at") is not None,
        added_at=_timestamp(row.get("inserted_at")),
    )


def _item(row: dict[str, Any]) -> PinchflatItem:
    return PinchflatItem(
        id=row["id"], source_id=row["source_id"], media_id=str(row["media_id"]), title=row.get("title"),
        media_filepath=row.get("media_filepath") or None, uploaded_at=row.get("uploaded_at"),
        playlist_index=_int(row.get("playlist_index")), upload_date_index=_int(row.get("upload_date_index")),
        prevent_download=_bool(row.get("prevent_download")), culled_at=row.get("culled_at"),
        prevent_culling=_bool(row.get("prevent_culling")),
        livestream=_bool(row.get("livestream")), short_form_content=_bool(row.get("short_form_content")),
        subtitle_filepaths=_subtitles(row.get("subtitle_filepaths")),
        thumbnail_filepath=row.get("thumbnail_filepath"), metadata_filepath=row.get("metadata_filepath"),
        nfo_filepath=row.get("nfo_filepath"),
    )


def _settings(rows: list[dict[str, Any]]) -> PinchflatSettings:
    row = rows[0] if rows else {}
    sleep = row.get("extractor_sleep_interval_seconds")
    return PinchflatSettings(
        restrict_filenames=_bool(row.get("restrict_filenames")),
        extractor_sleep_interval_seconds=float(sleep) if sleep not in (None, "") else None,
        download_throughput_limit=row.get("download_throughput_limit") or None,
        youtube_api_key=(row.get("youtube_api_key") or "").strip() or None,
        apprise_server=(row.get("apprise_server") or "").strip() or None,
        yt_dlp_version=row.get("yt_dlp_version"),
    )


def read_pinchflat(copy: Path) -> PinchflatData:
    """Read the private copy made by :func:`private_copy`."""
    connection = _connect(copy)
    try:
        version = check_version(connection)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return PinchflatData(
            version=version,
            profiles=tuple(_profile(row) for row in _rows(connection, "media_profiles")),
            sources=tuple(_source(row) for row in _rows(connection, "sources")),
            items=tuple(_item(row) for row in _rows(connection, "media_items")),
            settings=_settings(_rows(connection, "settings") if "settings" in tables else []),
            metadata_files={
                int(row["media_item_id"]): str(row["metadata_filepath"])
                for row in (_rows(connection, "media_metadata") if "media_metadata" in tables else [])
                if row.get("media_item_id") is not None and row.get("metadata_filepath")
            },
        )
    finally:
        connection.close()
