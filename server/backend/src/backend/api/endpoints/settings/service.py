from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic.alias_generators import to_snake
from pydantic_settings import DotEnvSettingsSource, EnvSettingsSource
from yaml.nodes import MappingNode, ScalarNode

from backend.api.models.settings import (
    DownloadStorageInspectionValue,
    FilesystemInspectionValue,
    SettingFieldPath,
    SettingsAPIRead,
    SettingsAPIUpdate,
    SettingsValues,
    UI_SETTING_PATHS,
)
from config import get_settings, replace_settings
from backend.utils.filesystem_storage import inspect_filesystem, same_filesystem
from config.settings.base import get_config_path
from config.settings.settings import (
    AppSettings,
    TIMEZONE_ENVIRONMENT_VARIABLE,
    environment_settings_source_data,
)


logger = logging.getLogger(__name__)
_SETTINGS_FILE_LOCK = threading.RLock()
_MISSING = object()


class SettingsPersistenceError(RuntimeError):
    """Raised when config.yml cannot be changed safely."""


class SettingsManagedByEnvironmentError(RuntimeError):
    """Raised when a caller tries to change an environment-managed setting."""


@dataclass(frozen=True)
class _SettingsRuntimeState:
    settings: AppSettings
    values: SettingsValues
    configured_fields: tuple[SettingFieldPath, ...]
    environment_overrides: dict[str, str]
    download_storage: DownloadStorageInspectionValue
    updated_at: datetime | None


class _SettingsRuntimeRegistry:
    """Thread-safe owner of the Settings UI runtime snapshot."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state: _SettingsRuntimeState | None = None

    def get(self) -> _SettingsRuntimeState:
        with self._lock:
            settings = get_settings()
            if self._state is None or self._state.settings is not settings:
                self._state = _build_runtime_state(settings)
            return self._state

    def install(self, state: _SettingsRuntimeState) -> None:
        with self._lock:
            replace_settings(state.settings)
            self._state = state


_SETTINGS_RUNTIME = _SettingsRuntimeRegistry()


def _file_timestamp(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _path_candidates(segment: str) -> tuple[str, ...]:
    snake = to_snake(segment)
    return (segment,) if snake == segment else (segment, snake)


def _get_document_value(document: dict[str, Any], path: str) -> Any:
    current: Any = document
    for segment in path.split("."):
        if not isinstance(current, dict):
            return _MISSING
        key = next((candidate for candidate in _path_candidates(segment) if candidate in current), None)
        if key is None:
            return _MISSING
        current = current[key]
    return current



def _set_document_value(document: dict[str, Any], path: str, value: Any) -> None:
    segments = path.split(".")
    current = document
    for segment in segments[:-1]:
        child = current.get(segment)
        if not isinstance(child, dict):
            child = {}
            current[segment] = child
        current = child
    current[segments[-1]] = value


def _load_config_document(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "", {}
    except OSError as exc:
        raise SettingsPersistenceError(f"WireLoft could not read {path}.") from exc

    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SettingsPersistenceError("config.yml contains invalid YAML.") from exc

    if loaded is None:
        return text, {}
    if not isinstance(loaded, dict):
        raise SettingsPersistenceError("config.yml must contain a YAML mapping at its root.")
    return text, loaded


def _configured_fields(document: dict[str, Any]) -> tuple[SettingFieldPath, ...]:
    return tuple(
        cast(SettingFieldPath, path)
        for path in UI_SETTING_PATHS
        if _get_document_value(document, path) is not _MISSING
    )


def _environment_variable_name(path: str) -> str:
    if path == "timezone":
        return TIMEZONE_ENVIRONMENT_VARIABLE
    return "WL_" + "__".join(to_snake(segment).upper() for segment in path.split("."))


def _source_document(source) -> dict[str, Any]:
    try:
        return environment_settings_source_data(source, AppSettings)
    except Exception:
        logger.exception("Failed to inspect a settings environment source")
        return {}


def _environment_overrides() -> dict[str, str]:
    """Return UI paths whose effective values are controlled above config.yml.

    Both process environment variables and WireLoft's configured .env file are
    included because neither can be overridden by editing config.yml. All app
    settings use WL_* names except timezone, which is managed by the standard
    container-level TZ variable.
    """
    source_documents = [
        _source_document(EnvSettingsSource(AppSettings)),
        _source_document(DotEnvSettingsSource(AppSettings)),
    ]

    managed: dict[str, str] = {}
    for path in UI_SETTING_PATHS:
        if not any(_get_document_value(document, path) is not _MISSING for document in source_documents):
            continue

        canonical_name = _environment_variable_name(path)
        if path == "timezone":
            managed[path] = canonical_name
            continue

        parent_name = "WL_" + to_snake(path.split(".", 1)[0]).upper()
        actual_name = next(
            (
                name
                for name in os.environ
                if name.upper() in {canonical_name.upper(), parent_name.upper()}
            ),
            canonical_name,
        )
        managed[path] = actual_name
    return managed


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None

    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        try:
            os.chmod(temporary_path, 0o600)
        except (OSError, PermissionError, NotImplementedError):
            pass

        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _find_mapping_value(node: MappingNode, segment: str):
    candidates = set(_path_candidates(segment))
    for key_node, value_node in node.value:
        if isinstance(key_node, ScalarNode) and str(key_node.value) in candidates:
            return key_node, value_node
    return None


def _serialize_yaml_scalar(value: Any) -> str:
    """Serialize a UI value as a single YAML-safe scalar.

    JSON scalar syntax is valid YAML and avoids PyYAML's document terminator for
    scalar-only dumps while still correctly quoting paths, URLs and cron strings.
    """
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _append_text(text: str, addition: str) -> str:
    if text and not text.endswith("\n"):
        text += "\n"
    return text + addition


@dataclass(frozen=True)
class _TextEdit:
    start: int
    end: int
    replacement: str


def _patch_config_scalars(text: str, changes: dict[str, Any]) -> str:
    """Apply all Settings scalar edits after parsing the YAML syntax tree once."""
    try:
        root = yaml.compose(text) if text.strip() else None
    except yaml.YAMLError as exc:
        raise SettingsPersistenceError("config.yml contains invalid YAML.") from exc

    if root is not None and not isinstance(root, MappingNode):
        raise SettingsPersistenceError("config.yml must contain a YAML mapping at its root.")

    edits: list[_TextEdit] = []
    section_insertions: dict[int, list[str]] = {}
    root_additions: list[str] = []
    missing_sections: dict[str, list[str]] = {}

    for path, value in changes.items():
        serialized = _serialize_yaml_scalar(value)
        segments = path.split(".")
        if len(segments) not in {1, 2}:
            raise SettingsPersistenceError(f"Unsupported settings path: {path}")

        if len(segments) == 1:
            existing = _find_mapping_value(root, segments[0]) if isinstance(root, MappingNode) else None
            if existing is None:
                root_additions.append(f"{segments[0]}: {serialized}\n")
                continue
            _key_node, value_node = existing
            if not isinstance(value_node, ScalarNode):
                raise SettingsPersistenceError(f"{path} must be a scalar setting in config.yml.")
            edits.append(_TextEdit(value_node.start_mark.index, value_node.end_mark.index, serialized))
            continue

        section_name, field_name = segments
        section_entry = _find_mapping_value(root, section_name) if isinstance(root, MappingNode) else None
        if section_entry is None:
            missing_sections.setdefault(section_name, []).append(
                f"  {field_name}: {serialized}\n"
            )
            continue

        _section_key, section_value = section_entry
        if isinstance(section_value, ScalarNode) and section_value.value in {"", "null", "~"}:
            section_insertions.setdefault(section_value.end_mark.index, []).append(
                f"  {field_name}: {serialized}\n"
            )
            continue
        if not isinstance(section_value, MappingNode):
            raise SettingsPersistenceError(f"{section_name} must be a mapping in config.yml.")
        if section_value.flow_style:
            raise SettingsPersistenceError(
                f"{section_name} must use a block mapping in config.yml before it can be edited in Settings."
            )

        field_entry = _find_mapping_value(section_value, field_name)
        if field_entry is not None:
            _field_key, field_value = field_entry
            if not isinstance(field_value, ScalarNode):
                raise SettingsPersistenceError(f"{path} must be a scalar setting in config.yml.")
            edits.append(_TextEdit(field_value.start_mark.index, field_value.end_mark.index, serialized))
            continue

        section_insertions.setdefault(section_value.end_mark.index, []).append(
            f"  {field_name}: {serialized}\n"
        )

    for index, additions in section_insertions.items():
        prefix = "" if index == 0 or text[index - 1] == "\n" else "\n"
        edits.append(_TextEdit(index, index, prefix + "".join(additions)))

    for edit in sorted(edits, key=lambda item: (item.start, item.end), reverse=True):
        text = text[:edit.start] + edit.replacement + text[edit.end:]

    additions = list(root_additions)
    for section_name, section_values in missing_sections.items():
        additions.append(f"{section_name}:\n{''.join(section_values)}")
    if additions:
        text = _append_text(text, "".join(additions))

    return text


def _value_for_path(values_document: dict[str, Any], path: str) -> Any:
    value = _get_document_value(values_document, path)
    if value is _MISSING:
        raise SettingsPersistenceError(f"Settings value missing for {path}.")
    return value


def _download_storage(settings: AppSettings) -> DownloadStorageInspectionValue:
    download_settings = settings.download_settings
    download_root = inspect_filesystem(download_settings.download_root)
    temporary_root = inspect_filesystem(download_settings.temporary_download_root)
    return DownloadStorageInspectionValue(
        download_root=FilesystemInspectionValue(
            path=str(download_root.path),
            mount_point=str(download_root.mount_point) if download_root.mount_point is not None else None,
            filesystem_type=download_root.filesystem_type,
            storage_kind=download_root.storage_kind,
        ),
        temporary_download_root=FilesystemInspectionValue(
            path=str(temporary_root.path),
            mount_point=str(temporary_root.mount_point) if temporary_root.mount_point is not None else None,
            filesystem_type=temporary_root.filesystem_type,
            storage_kind=temporary_root.storage_kind,
        ),
        same_filesystem=same_filesystem(
            download_settings.download_root,
            download_settings.temporary_download_root,
        ),
    )


def _build_runtime_state(settings: AppSettings) -> _SettingsRuntimeState:
    path = get_config_path()
    _text, document = _load_config_document(path)
    return _SettingsRuntimeState(
        settings=settings,
        values=SettingsValues.from_app_settings(settings),
        configured_fields=_configured_fields(document),
        environment_overrides=_environment_overrides(),
        download_storage=_download_storage(settings),
        updated_at=_file_timestamp(path),
    )


def initialize_settings_runtime_state() -> None:
    """Snapshot Settings metadata once so external source edits require restart."""
    _SETTINGS_RUNTIME.get()


def _runtime_state() -> _SettingsRuntimeState:
    return _SETTINGS_RUNTIME.get()


def _response(state: _SettingsRuntimeState) -> SettingsAPIRead:
    return SettingsAPIRead(
        values=state.values,
        configured_fields=list(state.configured_fields),
        environment_overrides=dict(state.environment_overrides),
        download_storage=state.download_storage,
        updated_at=state.updated_at,
    )


def get_ui_settings() -> SettingsAPIRead:
    """Return the current in-memory settings snapshot without rereading sources."""
    return _response(_runtime_state())


def save_ui_settings(body: SettingsAPIUpdate) -> SettingsAPIRead:
    with _SETTINGS_FILE_LOCK:
        state = _runtime_state()
        path = get_config_path()
        blocked = [field for field in body.changed_fields if field in state.environment_overrides]
        if blocked:
            variables = ", ".join(state.environment_overrides[field] for field in blocked)
            raise SettingsManagedByEnvironmentError(
                f"These settings are managed by environment variables: {variables}."
            )

        try:
            previous_content = path.read_bytes()
            text = previous_content.decode("utf-8")
            previous_file_existed = True
        except FileNotFoundError:
            previous_content = None
            text = ""
            previous_file_existed = False
        except (OSError, UnicodeDecodeError) as exc:
            raise SettingsPersistenceError(f"VodLoft could not read {path}.") from exc

        values_document = body.values.to_config_document()
        changes = {
            field: _value_for_path(values_document, field)
            for field in body.changed_fields
        }

        try:
            patched_text = _patch_config_scalars(text, changes)

            # Revalidate from the current runtime snapshot plus only the accepted
            # UI changes. This deliberately does not re-read config.yml, .env or
            # process environment: external source changes take effect on restart.
            effective_document = state.settings.model_dump(mode="python", by_alias=True)
            for field, value in changes.items():
                _set_document_value(effective_document, field, value)
            effective_settings = AppSettings.model_validate(effective_document)

            _atomic_write(path, patched_text.encode("utf-8"))

            configured_fields = tuple(dict.fromkeys((*state.configured_fields, *body.changed_fields)))
            storage_fields = {
                "downloadSettings.downloadRoot",
                "downloadSettings.temporaryDownloadRoot",
            }
            next_state = _SettingsRuntimeState(
                settings=effective_settings,
                values=SettingsValues.from_app_settings(effective_settings),
                configured_fields=configured_fields,
                environment_overrides=state.environment_overrides,
                download_storage=(
                    _download_storage(effective_settings)
                    if storage_fields.intersection(body.changed_fields)
                    else state.download_storage
                ),
                updated_at=_file_timestamp(path),
            )
            _SETTINGS_RUNTIME.install(next_state)
            logging.getLogger().setLevel(
                getattr(logging, effective_settings.log_level, logging.INFO)
            )
            return _response(next_state)
        except Exception as exc:
            logger.exception("Failed to persist settings to config.yml")
            try:
                if previous_content is not None:
                    _atomic_write(path, previous_content)
                elif not previous_file_existed:
                    path.unlink(missing_ok=True)
                _SETTINGS_RUNTIME.install(state)
            except Exception:
                logger.exception("Failed to restore the previous config.yml")
            if isinstance(exc, SettingsPersistenceError):
                raise
            raise SettingsPersistenceError(
                "VodLoft could not save config.yml. Check the config file and directory permissions."
            ) from exc

