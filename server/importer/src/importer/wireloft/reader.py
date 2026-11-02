"""Read a private copy of a WireLoft database, at any WireLoft release from 1.0 on.

The copy is first brought to the newest WireLoft schema with WireLoft's own
migrations (``importer.wireloft.migrations``), so everything after that reads
one schema. WireLoft's settings come from its config.yml, and its Daily Wire
sign-in from the keyring file next to it.
"""
from __future__ import annotations

import base64
import configparser
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlalchemy as sa
import yaml

from . import migrations
from .migrations import Release, UnknownWireLoftRelease


class WireLoftReadError(ValueError):
    """The upload is not a WireLoft database this VODLoft can read; the message says why."""


# WireLoft's own background updates, and the release that brought each. One
# that has not run yet leaves older data behind, such as older episode numbers.
BACKGROUND_UPDATES = (
    ("f6a1c3d8b427", "Refresh historical episode identifiers"),
    ("3c8f6a1d2b47", "Populate show square thumbnails"),
    ("b7d2f49c0a13", "Episode download delay setting"),
)
_BACKGROUND_SINCE = {"f6a1c3d8b427": "6d4a8c1f2b90", "3c8f6a1d2b47": "6d4a8c1f2b90", "b7d2f49c0a13": "a4e7c19b2d53"}

TABLES = (
    "shows", "seasons", "media_items", "media_items_episode", "media_items_movie", "movie_extra_sources",
    "media_items_movie_extra", "local_media_profiles", "local_media_profiles_show", "local_media_profiles_movie",
    "download_profiles", "download_profiles_podcast", "download_profiles_series", "download_profile_series_seasons",
    "stream_profiles", "stream_profiles_rss", "media_downloads", "media_downloads_episode", "media_downloads_movie",
    "media_downloads_movie_extra", "media_download_history", "media_download_assets", "custom_index_states",
    "show_local_assets", "metadata",
)

KEYRING_FILE = "keyring/data/python_keyring/keyring_pass.cfg"
_KEYRING_SERVICE = "wireloft-dailywire-auth"


@dataclass
class WireLoftData:
    release: Release
    upgraded_from: Release
    tables: dict[str, list[dict[str, Any]]]
    background_version: str | None
    config: dict[str, Any] = field(default_factory=dict)
    """config.yml as WireLoft read it (camelCase keys), or empty."""
    sign_in: dict[str, str] = field(default_factory=dict)
    """The Daily Wire sign-in records by their store key, as JSON text."""

    def rows(self, table: str) -> list[dict[str, Any]]:
        return self.tables.get(table, [])

    def metadata(self, parent_table: str) -> dict[int, dict[str, str]]:
        found: dict[int, dict[str, str]] = {}
        for row in self.rows("metadata"):
            if row["parent_table"] == parent_table:
                found.setdefault(int(row["parent_id"]), {})[row["key"]] = row["value"]
        return found

    def pending_background_updates(self) -> list[str]:
        """WireLoft's background updates this database's release has but has not finished."""
        order = [revision for revision, _title in BACKGROUND_UPDATES]
        done = order.index(self.background_version) + 1 if self.background_version in order else 0
        releases = [item.revision for item in migrations.RELEASES]
        reached = releases.index(self.upgraded_from.revision)
        return [
            title for revision, title in BACKGROUND_UPDATES[done:]
            if releases.index(_BACKGROUND_SINCE[revision]) <= reached
        ]


def _unescape_keyring(value: str) -> str:
    """keyrings.alt writes every character outside [A-Za-z0-9] as _XX (hex)."""
    return re.sub(rb"_([0-9A-Fa-f]{2})", lambda match: bytes([int(match.group(1), 16)]), value.encode()).decode()


def read_sign_in(keyring_file: Path) -> dict[str, str]:
    """The Daily Wire sign-in WireLoft keeps in keyrings.alt's plaintext keyring."""
    parser = configparser.RawConfigParser()
    try:
        parser.read(keyring_file, encoding="utf-8")
    except configparser.Error:
        return {}
    found: dict[str, str] = {}
    for section in parser.sections():
        if _unescape_keyring(section) != _KEYRING_SERVICE:
            continue
        for option, value in parser.items(section):
            try:
                record = base64.b64decode(value).decode("utf-8")
                json.loads(record)
            except (ValueError, UnicodeDecodeError):
                continue
            found[_unescape_keyring(option)] = record
    return found


def read_config(config_file: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _check(copy: Path) -> None:
    try:
        connection = sqlite3.connect(copy)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise WireLoftReadError(f"This is not a database SQLite can open: {exc}") from exc
    if result is None or result[0] != "ok":
        raise WireLoftReadError(
            "The database copy is damaged, which happens when WireLoft writes while it is copied. "
            "Stop WireLoft and upload it again."
        )
    if not {"shows", "local_media_profiles", "settings"} <= tables:
        raise WireLoftReadError("This is not a WireLoft database: it has no shows or Local Media Profiles.")


def read_wireloft(copy: Path, *, config: Path | None = None, keyring_file: Path | None = None) -> WireLoftData:
    """Upgrade the private copy at ``copy`` to the newest WireLoft schema and read it.

    ``config`` is the upload's config.yml, which the WireLoft 1.0 migration
    rewrites in the copy as WireLoft itself did.
    """
    _check(copy)
    engine = sa.create_engine(f"sqlite:///{copy.as_posix()}")
    try:
        with engine.connect() as connection:
            revision = migrations.stored_revision(connection)
    finally:
        engine.dispose()
    try:
        found = migrations.release(revision)
    except UnknownWireLoftRelease as exc:
        raise WireLoftReadError(str(exc)) from exc
    try:
        migrations.upgrade(copy, config=config if config is not None and config.is_file() else None)
    except Exception as exc:  # noqa: BLE001  (WireLoft's migrations raise many kinds)
        raise WireLoftReadError(f"WireLoft's own upgrade of the copy from {found.label} failed: {exc}") from exc

    connection = sqlite3.connect(copy)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            table: [dict(row) for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
            for table in TABLES
        }
        background = connection.execute("SELECT background_migration_version FROM settings ORDER BY id").fetchone()
    finally:
        connection.close()
    return WireLoftData(
        release=migrations.release(migrations.HEAD),
        upgraded_from=found,
        tables=tables,
        background_version=background[0] if background else None,
        config=read_config(config) if config is not None and config.is_file() else {},
        sign_in=read_sign_in(keyring_file) if keyring_file is not None and keyring_file.is_file() else {},
    )
