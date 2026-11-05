"""WireLoft rows -> ImportPlan.

VODLoft was forked from WireLoft, so a WireLoft record is a VODLoft record from
before VODLoft's own changes. The mapping makes those changes the way VODLoft's
migrations made them for a database it took over: shows become Collections,
podcast and series Download Profiles become one Download Profile, output
templates name ``collection_*`` instead of ``show_*`` variables, and so on.
Daily Wire ids, episode numbers, Custom Index assignments and feed tokens are
kept as they are, so file names and feed addresses stay the same.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from jinja2 import Environment, TemplateSyntaxError

from ..contract import (
    CustomIndexPlan,
    ImportLocation,
    ImportPlan,
    ImportWarning,
    ProfilePlan,
    RecordPlan,
    Reference,
    SettingPlan,
)
from ..paths import DEFAULT_PATH_MAP, PathMap, map_path
from ..uploads import UploadFile
from .reader import KEYRING_FILE, WireLoftData, read_wireloft

SOURCE = "dailywire"

# Output template variables that named the show (VODLoft 0.6.0's rename).
_TEMPLATE_NAMES = {"show": "collection", "show_title": "collection_title"}
_TEMPLATE_PREFIXES = (("meta_show_", "meta_collection_"),)
# Stored values VODLoft renamed (VODLoft's stored-names migration).
_MEMBERSHIP_LEVELS = {"WL_ANY": "HIGHEST_ALLOWED"}
_HISTORY_ACTIONS = {"cancelled": "canceled"}
_PUBLISH_STATUSES = {"dw_processing": "source_processing", "published_with_countdown": "published_preliminary"}
_METADATA_KEYS = {"ep_status.dw_processing.slug": "ep_status.source_processing.slug"}
_VALUE_PREFIXES = (
    ("wireloft:last_known_pending:", "vodloft:last_known_pending:"),
    ("wireloft:recorded_published_final:", "vodloft:recorded_published_final:"),
)
_SOURCE_SLUG_KEY = "source.slug"
_INDEX_DEFINITION = "custom_index.definition."
_INDEX_KEEP_NUMBERS = "custom_index.keep_numbers."
_INDEX_ASSIGNMENT = re.compile(r"^custom_index\.(?P<profile>\d+)\.(?P<key>[a-z_][a-z0-9_-]*)$")

_ROW_KEYS = {"id", "created_at", "updated_at"}
_EPISODE_FIELDS = (
    "index", "episode_identifier", "slug", "publish_status", "video_url", "audio_url", "sharing_url",
    "went_live_date", "published_date", "scheduled_date", "metadata_is_final", "title", "description", "duration",
    "background_image_path", "thumbnail_landscape_path", "thumbnail_portrait_path", "thumbnail_square_path",
    "dw_episode_number",
)
_DOWNLOAD_FIELDS = (
    "downloaded_bytes", "format_downloaded", "artifact_status", "artifact_error", "automatic_retry_suppressed",
    "downloaded_at", "artifact_stat_dev", "artifact_stat_ino", "artifact_size_bytes", "artifact_fingerprint",
)
_PROFILE_SETTINGS = (
    "preferred_format", "append_media_type_to_filename", "download_mode", "thumbnail_mode", "metadata_mode",
    "subtitle_mode",
)

# config.yml sections the import offers, by VODLoft's settings names.
_SETTINGS_SECTIONS = {
    "downloadSettings": "download_settings",
    "scheduler": "scheduler",
    "newEpisodeSchedule": "new_episode_schedule",
    "episodeStatusTiming": "episode_status_timing",
    "fileWatcher": "file_watcher",
}
# Folders inside WireLoft's container: VODLoft keeps its own.
_FOLDER_SETTINGS = {"downloadRoot", "temporaryDownloadRoot", "rssCacheRoot", "ffmpegPath"}


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).lower()


def _collection_word(name: str) -> str:
    return re.sub(r"(?<![a-z])show(s?)(?![a-z])", lambda match: "collection" + match.group(1), name)


def rename_template_variables(source: str) -> str:
    """Rename WireLoft's show variables in one output template, leaving all other text as it is."""
    try:
        tokens = list(Environment().lex(source))
    except TemplateSyntaxError:
        return source
    if "".join(value for _, _, value in tokens) != source:
        return source
    parts = []
    for _, kind, value in tokens:
        if kind == "name":
            if value in _TEMPLATE_NAMES:
                value = _TEMPLATE_NAMES[value]
            else:
                for old, new in _TEMPLATE_PREFIXES:
                    if value.startswith(old):
                        value = new + value[len(old):]
        parts.append(value)
    return "".join(parts)


def _value(value: str) -> str:
    for old, new in _VALUE_PREFIXES:
        if value.startswith(old):
            return new + value[len(old):]
    return value


def _publish_status(value: object) -> object:
    return _PUBLISH_STATUSES.get(value, value) if isinstance(value, str) else value


def _history_metadata(value: object) -> object:
    metadata = _json(value)
    if isinstance(metadata, dict) and "started_publish_status" in metadata:
        return {**metadata, "started_publish_status": _publish_status(metadata["started_publish_status"])}
    return metadata


def _ref(kind: str, row_id: object) -> Reference:
    return Reference(kind, str(row_id))


def _profile_ref(row_id: object) -> Reference:
    return Reference("profile", f"local_media_profile:{row_id}")


def _by_id(rows: Iterable[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    return {int(row["id"]): row for row in rows}


def _json(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


class _Paths:
    """Maps WireLoft's paths to the folders VODLoft sees, and remembers what it could not map."""

    def __init__(self, path_map: PathMap) -> None:
        self.path_map = path_map
        self.unmapped = 0

    def __call__(self, path: object) -> str | None:
        if not path:
            return None
        mapped = map_path(str(path), self.path_map)
        if mapped is None:
            self.unmapped += 1
        return mapped


# Profiles ---------------------------------------------------------------------

def _profiles(data: WireLoftData) -> tuple[ProfilePlan, ...]:
    show_profiles = _by_id(data.rows("local_media_profiles_show"))
    profile_meta = data.metadata("local_media_profiles")
    plans = []
    for row in data.rows("local_media_profiles"):
        profile_id = int(row["id"])
        meta = profile_meta.get(profile_id, {})
        kind = "collection" if row["type"] == "show" else str(row["type"])
        settings: dict[str, object] = {name: row[name] for name in _PROFILE_SETTINGS if row.get(name) is not None}
        settings["type"] = kind
        if kind == "collection" and profile_id in show_profiles:
            settings["collection_scope"] = show_profiles[profile_id]["show_scope"]
            if show_profiles[profile_id].get("download_show_assets") is not None:
                settings["download_collection_assets"] = bool(show_profiles[profile_id]["download_show_assets"])
        indexes = tuple(
            CustomIndexPlan(key[len(_INDEX_DEFINITION):], name, meta.get(_INDEX_KEEP_NUMBERS + key[len(_INDEX_DEFINITION):]) == "1")
            for key, name in sorted(meta.items()) if key.startswith(_INDEX_DEFINITION)
        )
        template = rename_template_variables(str(row["output_template"]))
        plans.append(ProfilePlan(
            external_id=f"local_media_profile:{profile_id}",
            name=str(row["name"]),
            output_template=template,
            custom_indexes=indexes,
            settings=settings,
            original_template=str(row["output_template"]),
            report=("The show variables became collection variables",) if template != row["output_template"] else (),
        ))
    return tuple(plans)


# Records ----------------------------------------------------------------------

def _metadata(rows: Mapping[str, str] | None) -> dict[str, str]:
    return {key: _value(value) for key, value in (rows or {}).items()}


def _collections(data: WireLoftData, paths: _Paths) -> list[RecordPlan]:
    meta = data.metadata("shows")
    records = []
    for row in data.rows("shows"):
        values = {name: value for name, value in row.items() if name not in _ROW_KEYS}
        values["membership_level"] = _MEMBERSHIP_LEVELS.get(str(values["membership_level"]), values["membership_level"])
        values["source_key"] = SOURCE
        records.append(RecordPlan(
            "collection", str(row["id"]), values=values,
            identity={"source_key": SOURCE, "uuid": row["uuid"]},
            metadata=_metadata(meta.get(int(row["id"]))),
        ))
    return records


def _seasons(data: WireLoftData) -> list[RecordPlan]:
    return [
        RecordPlan(
            "season", str(row["id"]),
            values={name: row[name] for name in ("index", "slug", "name", "season_type", "season_number")},
            references={"collection_id": _ref("collection", row["show_id"])},
            identity={"collection_id": _ref("collection", row["show_id"]), "slug": row["slug"]},
        )
        for row in data.rows("seasons")
    ]


def _split_episode_metadata(meta: Mapping[str, str]) -> tuple[dict[str, str], tuple[tuple[str, str, str, str], ...]]:
    own: dict[str, str] = {}
    assignments: list[tuple[str, str, str, str]] = []
    for key, value in meta.items():
        match = _INDEX_ASSIGNMENT.match(key)
        if match:
            assignments.append((f"local_media_profile:{match['profile']}", "custom_index.", f".{match['key']}", value))
        elif key != _SOURCE_SLUG_KEY:
            own[_METADATA_KEYS.get(key, key)] = _value(value)
    return own, tuple(assignments)


def _episodes(data: WireLoftData) -> list[RecordPlan]:
    items = _by_id(data.rows("media_items"))
    meta = data.metadata("media_items_episode")
    records = []
    for row in data.rows("media_items_episode"):
        episode_id = int(row["id"])
        item = items[episode_id]
        episode_meta = meta.get(episode_id, {})
        own, assignments = _split_episode_metadata(episode_meta)
        values = {name: row[name] for name in _EPISODE_FIELDS}
        values["publish_status"] = _publish_status(values["publish_status"])
        values.update(uuid=item["uuid"], type=item["type"], source_key=SOURCE,
                      source_slug=episode_meta.get(_SOURCE_SLUG_KEY) or row["slug"])
        records.append(RecordPlan(
            "episode", str(episode_id), values=values,
            references={"collection_id": _ref("collection", row["show_id"]), "season_id": _ref("season", row["season_id"])},
            identity={"source_key": SOURCE, "uuid": item["uuid"]},
            metadata=own, profile_metadata=assignments,
        ))
    return records


def _movies(data: WireLoftData) -> list[RecordPlan]:
    items = _by_id(data.rows("media_items"))
    movie_meta = data.metadata("media_items_movie")
    extra_meta = data.metadata("media_items_movie_extra")
    records: list[RecordPlan] = []
    for row in data.rows("media_items_movie"):
        item = items[int(row["id"])]
        values = {name: _json(value) for name, value in row.items() if name not in _ROW_KEYS | {"official_trailer_id"}}
        values.update(uuid=item["uuid"], type=item["type"], source_key=SOURCE)
        records.append(RecordPlan(
            "movie", str(row["id"]), values=values,
            identity={"source_key": SOURCE, "uuid": item["uuid"]},
            metadata=_metadata(movie_meta.get(int(row["id"]))),
        ))
    for row in data.rows("movie_extra_sources"):
        values = {name: _json(value) for name, value in row.items() if name != "id"}
        records.append(RecordPlan("movie_extra_source", str(row["id"]), values=values, identity={"slug": row["slug"]}))
    for row in data.rows("media_items_movie_extra"):
        item = items[int(row["id"])]
        records.append(RecordPlan(
            "movie_extra", str(row["id"]),
            values={"movie_extra_type": row["movie_extra_type"], "uuid": item["uuid"], "type": item["type"],
                    "source_key": SOURCE},
            references={"movie_id": _ref("movie", row["movie_id"]), "source_id": _ref("movie_extra_source", row["source_id"])},
            identity={"source_key": SOURCE, "uuid": item["uuid"]},
            metadata=_metadata(extra_meta.get(int(row["id"]))),
        ))
    # A movie names its official trailer, which is one of its extras: set once both exist.
    for row in data.rows("media_items_movie"):
        if row.get("official_trailer_id"):
            records.append(RecordPlan(
                "movie", str(row["id"]),
                references={"official_trailer_id": _ref("movie_extra", row["official_trailer_id"])},
            ))
    return records


def _download_profiles(data: WireLoftData) -> list[RecordPlan]:
    podcast = _by_id(data.rows("download_profiles_podcast"))
    series = _by_id(data.rows("download_profiles_series"))
    shows = _by_id(data.rows("shows"))
    seasons_by_show: dict[int, list[int]] = {}
    for season in data.rows("seasons"):
        seasons_by_show.setdefault(int(season["show_id"]), []).append(int(season["id"]))
    records: list[RecordPlan] = []
    for row in data.rows("download_profiles"):
        profile_id = int(row["id"])
        values: dict[str, object] = {
            "enable_profile": bool(row["enable_profile"]),
            "ep_id_type_list": _json(row["ep_id_type_list"]),
        }
        if profile_id in podcast:
            extra = podcast[profile_id]
            values.update({name: extra[name] for name in (
                "download_with_countdown", "redownload_final", "download_days_in_past", "download_episode_count",
                "download_starting_from", "delete_older_episodes",
            )})
        if profile_id in series:
            values["include_upcoming_seasons"] = bool(series[profile_id]["include_upcoming_seasons"])
        references = {
            "collection_id": _ref("collection", row["show_id"]),
            "local_media_profile_id": _profile_ref(row["local_media_profile_id"]),
        }
        records.append(RecordPlan(
            "download_profile", str(profile_id), values=values, references=references,
            identity={"collection_id": references["collection_id"], "local_media_profile_id": references["local_media_profile_id"]},
        ))
        # A series profile listed its seasons; a podcast profile of a seasonal show
        # downloaded every season, which is now a filter on every season it has.
        if profile_id in series:
            season_ids = [int(link["season_id"]) for link in data.rows("download_profile_series_seasons")
                          if int(link["download_profiles_series_id"]) == profile_id]
        elif shows.get(int(row["show_id"]), {}).get("episode_identifier") == "seasonal":
            season_ids = seasons_by_show.get(int(row["show_id"]), [])
        else:
            season_ids = []
        for season_id in season_ids:
            link = {"download_profile_id": _ref("download_profile", profile_id), "season_id": _ref("season", season_id)}
            records.append(RecordPlan("download_profile_season", f"{profile_id}:{season_id}", references=link, identity=link))
    return records


def _stream_profiles(data: WireLoftData) -> list[RecordPlan]:
    rss = _by_id(data.rows("stream_profiles_rss"))
    records = []
    for row in data.rows("stream_profiles"):
        if row["type"] != "rss" or int(row["id"]) not in rss:
            continue
        extra = rss[int(row["id"])]
        values = {name: _json(value) for name, value in row.items() if name not in _ROW_KEYS | {"show_id", "overwrite_show_title"}}
        values["overwrite_collection_title"] = row.get("overwrite_show_title")
        values.update({name: _json(value) for name, value in extra.items() if name != "id"})
        if "use_dw_stream" in values:
            values["use_source_stream"] = values.pop("use_dw_stream")
        records.append(RecordPlan(
            "stream_profile", str(row["id"]), values=values,
            references={"collection_id": _ref("collection", row["show_id"])},
            identity={"token": row["token"]},
        ))
    return records


_DOWNLOAD_ITEM_KINDS = {"episode": "episode", "movie": "movie", "movie_extra": "movie_extra"}


def _downloads(data: WireLoftData, paths: _Paths) -> list[RecordPlan]:
    episode_downloads = _by_id(data.rows("media_downloads_episode"))
    history: dict[int, list[Mapping[str, Any]]] = {}
    for row in data.rows("media_download_history"):
        history.setdefault(int(row["media_download_id"]), []).append(row)
    assets: dict[int, list[Mapping[str, Any]]] = {}
    for row in data.rows("media_download_assets"):
        assets.setdefault(int(row["media_download_id"]), []).append(row)
    meta = data.metadata("media_downloads")
    records = []
    for row in data.rows("media_downloads"):
        download_id = int(row["id"])
        kind = _DOWNLOAD_ITEM_KINDS.get(str(row["type"]))
        if kind is None:
            continue
        values: dict[str, object] = {name: row[name] for name in _DOWNLOAD_FIELDS}
        values.update(type=row["type"], file_path=paths(row["file_path"]), original_path=row["file_path"])
        references = {
            "media_item_id": _ref(kind, row["media_item_id"]),
            "local_media_profile_id": _profile_ref(row["local_media_profile_id"]),
        }
        if kind == "episode" and download_id in episode_downloads:
            extra = episode_downloads[download_id]
            values.update({name: extra[name] for name in ("redownload_when_final", "redownload_when_delay_passed")})
            values["downloaded_publish_status"] = _publish_status(extra["downloaded_publish_status"])
            if extra.get("download_profile_id"):
                references["download_profile_id"] = _ref("download_profile", extra["download_profile_id"])
        children = tuple(
            RecordPlan("download_history", str(item["id"]), values={
                "action": _HISTORY_ACTIONS.get(item["action"], item["action"]),
                "metadata": _history_metadata(item["metadata"]), "occurred_at": item["occurred_at"],
            })
            for item in history.get(download_id, [])
        ) + tuple(
            RecordPlan("download_asset", str(item["id"]), values={
                "asset_key": item["asset_key"], "kind": item["kind"], "path": paths(item["path"]),
                "suffix": item["suffix"], "size_bytes": item["size_bytes"], "fingerprint": item["fingerprint"],
            })
            for item in assets.get(download_id, [])
        )
        records.append(RecordPlan(
            "download", str(download_id), values=values, references=references,
            identity={"media_item_id": references["media_item_id"], "local_media_profile_id": references["local_media_profile_id"]},
            metadata=_metadata(meta.get(download_id)), children=children,
        ))
    return records


def _collection_records(data: WireLoftData, paths: _Paths) -> list[RecordPlan]:
    records = []
    for row in data.rows("custom_index_states"):
        references = {
            "collection_id": _ref("collection", row["show_id"]),
            "local_media_profile_id": _profile_ref(row["local_media_profile_id"]),
        }
        records.append(RecordPlan(
            "custom_index_state", str(row["id"]), references=references, identity=dict(references),
            values={"requested_generation": row["requested_generation"], "completed_generation": row["completed_generation"]},
        ))
    for row in data.rows("show_local_assets"):
        references = {
            "collection_id": _ref("collection", row["show_id"]),
            "local_media_profile_id": _profile_ref(row["local_media_profile_id"]),
        }
        file_path = paths(row["file_path"])
        records.append(RecordPlan(
            "collection_asset", str(row["id"]), references=references,
            identity={**references, "asset_type": row["asset_type"], "file_path": file_path},
            values={name: row[name] for name in (
                "asset_type", "source_url", "source_format", "content_hash", "pending_hash", "checked_at",
            )} | {"file_path": file_path},
        ))
    return records


# Settings ---------------------------------------------------------------------

def _settings(data: WireLoftData) -> list[SettingPlan]:
    settings: list[SettingPlan] = []
    for section, target in _SETTINGS_SECTIONS.items():
        values = data.config.get(section)
        if not isinstance(values, dict):
            continue
        for name, value in sorted(values.items()):
            key = f"settings.{target}.{_collection_word(_snake(name))}"
            if name in _FOLDER_SETTINGS:
                settings.append(SettingPlan(key, value, "unsupported", "A folder in WireLoft's container; VODLoft keeps its own"))
            elif isinstance(value, (dict, list)):
                continue
            else:
                settings.append(SettingPlan(key, value))
    movie_metadata = data.config.get("movieMetadata")
    if isinstance(movie_metadata, dict) and movie_metadata.get("tmdbReadAccessToken"):
        settings.append(SettingPlan(
            "settings.movie_metadata.tmdb_read_access_token", movie_metadata["tmdbReadAccessToken"], secret=True,
            note="The TMDB token WireLoft used for movie release dates",
        ))
    if data.sign_in:
        settings.append(SettingPlan(
            "dailywire.sign_in", dict(data.sign_in), secret=True,
            note="The Daily Wire sign-in, so VODLoft doesn't ask you to sign in again",
        ))
    return settings


# The plan ---------------------------------------------------------------------

def plan_import(data: WireLoftData, *, path_map: PathMap = DEFAULT_PATH_MAP) -> ImportPlan:
    paths = _Paths(path_map)
    records = [
        *_collections(data, paths), *_seasons(data), *_episodes(data), *_movies(data),
        *_download_profiles(data), *_stream_profiles(data), *_downloads(data, paths), *_collection_records(data, paths),
    ]
    warnings = []
    if data.upgraded_from.revision != data.release.revision:
        warnings.append(ImportWarning(
            "release", f"The database is from WireLoft {data.upgraded_from.label}; the import upgraded its copy "
            f"to WireLoft {data.release.label} first, as WireLoft would", "exact",
        ))
    for title in data.pending_background_updates():
        warnings.append(ImportWarning(
            "background_update", f"WireLoft had not finished its background update “{title}”. Start WireLoft once "
            "and let it finish, then upload again, or the import brings the older data over", "close",
        ))
    if paths.unmapped:
        warnings.append(ImportWarning(
            "paths", f"{paths.unmapped} file paths are outside the folder mapped to VODLoft's downloads; "
            "those downloads are kept but marked as not downloaded", "close",
        ))
    return ImportPlan(
        importer="wireloft",
        profiles=_profiles(data),
        records=tuple(records),
        settings=tuple(_settings(data)),
        warnings=tuple(warnings),
        version=f"{data.release.label} ({data.release.revision}), from {data.upgraded_from.label}",
    )


def download_paths(plan: ImportPlan) -> list[str]:
    """The WireLoft paths of the downloads in ``plan``, for finding the folder VODLoft sees them in."""
    return [
        str(record.values["original_path"]) for record in plan.records
        if record.kind == "download" and record.values.get("original_path")
        and record.values.get("artifact_status") == "available"
    ]


UPLOAD_FILES = (
    UploadFile("wireloft.db", required=True),
    UploadFile("wireloft.db-wal"),
    UploadFile("config.yml"),
    UploadFile(KEYRING_FILE, secret=True),
)


class WireLoftImporter:
    key = "wireloft"
    name = "WireLoft"
    upload_files = UPLOAD_FILES
    database = "wireloft.db"
    extras = "."

    def read(self, location: ImportLocation) -> ImportPlan:
        extras = location.extras
        data = read_wireloft(
            location.database,
            config=_private_config(location) if extras is not None else None,
            keyring_file=extras / KEYRING_FILE if extras is not None else None,
        )
        return plan_import(data, path_map=location.path_map)


def _private_config(location: ImportLocation) -> Path | None:
    """A copy of config.yml next to the database copy: the 1.0 migration may rewrite it."""
    import shutil

    assert location.extras is not None
    source = location.extras / "config.yml"
    if not source.is_file():
        return None
    copy = location.database.with_name("config.yml.copy")
    shutil.copyfile(source, copy)
    return copy

