"""Imports from other programs: preview a plan, apply it, and remember what it wrote.

An importer (``importer``) reads the other program's upload and describes it as
an ``ImportPlan``; this module decides what that becomes in VODLoft. Profiles
and Collections already linked by an earlier run are updated, a Collection
already in the Library is linked instead of added twice, and everything else is
created. Download Profiles come last, and stay off unless the person chose to
switch them on. Files are adopted where they are once their Collection's
episodes are indexed (``ImportStep``), so nothing is downloaded that is already
on disk.

The ledger (``ImportLink``) keeps a hash of each field as the import wrote it.
On a repeat run a field the person changed in VODLoft is kept, one only the
other program changed is updated, and a setting the import couldn't map before
is mapped once this VODLoft can.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import importer.pinchflat  # noqa: F401  (registers the importer)
from config import get_settings
from config.settings.submodels import FilenameRestrictionMode
from importer.contract import CollectionPlan, FilePlan, Importer, ImportPlan, ImportWarning, ProfilePlan
from importer.paths import DEFAULT_PATH_MAP, PathMap, detect_path_map, map_path, path_map_candidates
from importer.registry import get_importer as _registered_importer

from backend.db.models import (
    Collection, CollectionLocalMediaProfile, DownloadProfile, Episode, ImportLink, ImportRun, ImportStep,
    MediaDownloadBase,
)
from backend.db.models.media_download import EpisodeMediaDownload
from backend.services.adoption import AdoptionError, adopt, download_root, real_path
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.utils.custom_index import (
    INDEX_ASSIGNMENT_PREFIX, get_indexing_value_definitions, remove_episode_index_assignments,
    set_episode_index_assignment,
)
from backend.utils.output_template import (
    COLLECTION_OUTPUT_TEMPLATE_FIELDS, COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES, _date_substitutions,
    _sanitize_rendered_path, prepare_output_template, replace_output_extension,
)
from task_manager.events.transactional import queue_event

from .import_uploads import UploadError, remove_secrets, uploaded_at, work_location

logger = logging.getLogger(__name__)

RUNNING, WAITING, FINISHED, FAILED = "running", "waiting", "finished", "failed"
STEP_WAITING, STEP_DONE, STEP_FAILED = "waiting", "done", "failed"
_SAMPLES = 40
_PROOF_DIFFERENCES = 20
_PROFILE_FIELDS = (
    "output_template", "preferred_format", "subtitle_mode", "thumbnail_mode", "metadata_mode",
    "collection_scope", "download_collection_assets", "indexing_values",
)
_DOWNLOAD_PROFILE_FIELDS = (
    "ep_id_type_list", "download_days_in_past", "download_episode_count", "download_starting_from",
    "delete_older_episodes",
)
_DEFAULT_SETTINGS = frozenset({"downloads.filename_restriction_mode", "ytdlp.youtube_api_key"})


class ImportServiceError(ValueError):
    """The import can't run as asked."""


def get_importer(key: str) -> Importer:
    try:
        return _registered_importer(key)
    except KeyError as exc:
        raise ImportServiceError(f"VODLoft has no importer called {key}") from exc


@dataclass(frozen=True)
class ImportOptions:
    """What the person chose in the preview."""

    path_map: PathMap | None = None
    """None finds it from sample files."""
    collections: tuple[str, ...] | None = None
    """The external ids of the Collections to import; None imports all of them."""
    settings: tuple[str, ...] | None = None
    """The settings to apply; None applies the recommended ones."""
    enable_download_profiles: bool = False
    """Switch on the Download Profiles of the sources that were on in the other program."""
    templates: Mapping[str, str] = field(default_factory=dict)
    """Output templates the person edited, by profile external id."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_map": list(self.path_map) if self.path_map else None,
            "collections": list(self.collections) if self.collections is not None else None,
            "settings": list(self.settings) if self.settings is not None else None,
            "enable_download_profiles": self.enable_download_profiles,
            "templates": dict(self.templates),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ImportOptions":
        path_map = data.get("path_map")
        collections = data.get("collections")
        settings = data.get("settings")
        return cls(
            path_map=(str(path_map[0]), str(path_map[1])) if path_map else None,
            collections=tuple(collections) if collections is not None else None,
            settings=tuple(settings) if settings is not None else None,
            enable_download_profiles=bool(data.get("enable_download_profiles")),
            templates=dict(data.get("templates") or {}),
        )


@dataclass(frozen=True)
class LoadedPlan:
    plan: ImportPlan
    path_map: PathMap
    sampled: int
    found: int


# ---------- Reading the upload ----------

def _exists(virtual: str) -> bool:
    try:
        return real_path(virtual).is_file()
    except (AdoptionError, OSError):
        return False


def _vodloft_folders(depth: int = 2, limit: int = 400) -> list[str]:
    root = download_root()
    found: list[str] = []
    frontier = [root]
    for _level in range(depth):
        next_frontier: list[Path] = []
        for folder in frontier:
            try:
                children = sorted(child for child in folder.iterdir() if child.is_dir() and not child.name.startswith("."))
            except OSError:
                continue
            for child in children:
                found.append("/downloads/" + child.relative_to(root).as_posix())
                next_frontier.append(child)
                if len(found) >= limit:
                    return found
        frontier = next_frontier
    return found


def _samples(paths: Sequence[str]) -> list[str]:
    if len(paths) <= _SAMPLES:
        return list(paths)
    step = len(paths) / _SAMPLES
    return [paths[int(index * step)] for index in range(_SAMPLES)]


def _with_templates(plan: ImportPlan, templates: Mapping[str, str]) -> ImportPlan:
    if not templates:
        return plan
    profiles = tuple(
        replace(profile, output_template=templates[profile.external_id], support="close",
                report=(*profile.report, "The template was edited before the import"))
        if profile.external_id in templates else profile
        for profile in plan.profiles
    )
    return replace(plan, profiles=profiles)


def load_plan(importer: Importer, options: ImportOptions) -> LoadedPlan:
    """The importer's plan for the upload, with its files mapped to the folders VODLoft sees."""
    plan = importer.read(work_location(importer, DEFAULT_PATH_MAP))
    original = [file.path for file in plan.files if file.kind == "file" and file.path]
    samples = _samples(original)
    if options.path_map is not None:
        chosen = options.path_map
    else:
        chosen, _found = detect_path_map(samples, _exists, path_map_candidates(samples, _vodloft_folders()))
    if chosen != DEFAULT_PATH_MAP:
        plan = importer.read(work_location(importer, chosen))
    found = sum(1 for sample in samples if (mapped := map_path(sample, chosen)) and _exists(mapped))
    return LoadedPlan(_with_templates(plan, options.templates), chosen, len(samples), found)


# ---------- Ledger ----------

def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _links(session: Session, importer: str) -> dict[tuple[str, str], ImportLink]:
    return {
        (link.kind, link.external_id): link
        for link in session.scalars(select(ImportLink).where(ImportLink.importer == importer))
    }


@dataclass
class _Changes:
    """What a repeat run did to one VODLoft row, field by field."""

    updated: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    newly_mapped: list[str] = field(default_factory=list)


def _merge_fields(
    current: Mapping[str, object], wanted: Mapping[str, object], link: ImportLink | None,
    unsupported: Iterable[str],
) -> tuple[dict[str, object], dict[str, str], _Changes]:
    """The values to write, the hashes to remember, and what changed.

    Without a link everything is new. With one, a field whose current value no
    longer has the hash the import wrote was changed in VODLoft and is kept.
    """
    changes = _Changes()
    write: dict[str, object] = {}
    hashes: dict[str, str] = dict(link.written) if link is not None else {}
    for name, value in wanted.items():
        if link is None:
            write[name] = value
            hashes[name] = _hash(value)
            continue
        last = link.written.get(name)
        if last is not None and _hash(current.get(name)) != last:
            if _hash(current.get(name)) != _hash(value):
                changes.kept.append(name)
            else:
                hashes[name] = _hash(value)
            continue
        if _hash(current.get(name)) != _hash(value):
            write[name] = value
            changes.updated.append(name)
        hashes[name] = _hash(value)
    if link is not None:
        now = set(unsupported)
        changes.newly_mapped = sorted(set(link.unsupported) - now)
    return write, hashes, changes


def _unsupported(warnings: Iterable[ImportWarning]) -> list[str]:
    return sorted({warning.subject for warning in warnings if warning.support == "unsupported"})


def _remember(
    session: Session, links: dict[tuple[str, str], ImportLink], importer: str, kind: str, external_id: str,
    entity_id: int, hashes: dict[str, str], unsupported: list[str], run_id: int | None,
) -> ImportLink:
    link = links.get((kind, external_id))
    if link is None:
        link = ImportLink(importer=importer, kind=kind, external_id=external_id, written={}, unsupported=[])
        session.add(link)
        links[(kind, external_id)] = link
    link.entity_id, link.written, link.unsupported, link.run_id = entity_id, hashes, unsupported, run_id
    return link


# ---------- What each plan part becomes ----------

def _profile_values(profile: CollectionLocalMediaProfile) -> dict[str, object]:
    return {
        "output_template": profile.output_template,
        "preferred_format": profile.preferred_format,
        "subtitle_mode": profile.subtitle_mode,
        "thumbnail_mode": profile.thumbnail_mode,
        "metadata_mode": profile.metadata_mode,
        "collection_scope": profile.collection_scope,
        "download_collection_assets": profile.download_collection_assets,
        "indexing_values": [
            {"key": item.key, "name": item.name, "keep_numbers": item.keep_numbers}
            for item in get_indexing_value_definitions(profile)
        ],
    }


def _profile_wanted(plan: ProfilePlan) -> dict[str, object]:
    wanted = {name: plan.settings[name] for name in _PROFILE_FIELDS if name in plan.settings}
    wanted["output_template"] = plan.output_template
    wanted["indexing_values"] = [
        {"key": index.key, "name": index.name, "keep_numbers": index.keep_numbers} for index in plan.custom_indexes
    ]
    return wanted


def _download_profile_values(profile: DownloadProfile) -> dict[str, object]:
    values = {name: getattr(profile, name) for name in _DOWNLOAD_PROFILE_FIELDS}
    starting = values["download_starting_from"]
    values["download_starting_from"] = starting.isoformat() if isinstance(starting, date) else starting
    return values


def _download_profile_wanted(plan: CollectionPlan) -> dict[str, object]:
    return {name: (plan.download_profile or {}).get(name) for name in _DOWNLOAD_PROFILE_FIELDS}


def _normalise_url(url: str) -> str:
    try:
        from sources.ytdlp.source import collection_url

        url = collection_url(url)
    except Exception:  # noqa: BLE001  (a link yt-dlp can't read is compared as written)
        pass
    return url.strip().rstrip("/").lower().removeprefix("https://").removeprefix("http://").removeprefix("www.")


def _library_collections(session: Session) -> dict[str, Collection]:
    return {
        _normalise_url(collection.sharing_url): collection
        for collection in session.scalars(select(Collection).where(Collection.sharing_url.is_not(None)))
    }


def _matching_profile(session: Session, plan: ProfilePlan) -> CollectionLocalMediaProfile | None:
    """A VODLoft profile that names files the same way, to use instead of a copy."""
    if plan.output_template is None:
        return None
    return session.scalar(select(CollectionLocalMediaProfile).where(
        CollectionLocalMediaProfile.output_template == plan.output_template,
        CollectionLocalMediaProfile.preferred_format == plan.settings.get("preferred_format"),
    ).limit(1))


def _published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def path_proof(
    profile: ProfilePlan, files: Sequence[FilePlan], titles: Mapping[str, str], mode: FilenameRestrictionMode,
) -> dict[str, Any]:
    """How many of the files' real paths the converted template renders exactly."""
    adopted = [file for file in files if file.kind == "file" and file.path]
    if profile.output_template is None or not adopted:
        return {"identical": 0, "total": len(adopted), "differences": []}
    try:
        prepared = prepare_output_template(
            profile.output_template, allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS,
            allowed_metadata_scopes=COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
        )
    except ValueError as exc:
        return {"identical": 0, "total": len(adopted), "differences": [], "error": str(exc)}
    identical = 0
    differences: list[dict[str, str]] = []
    for file in adopted:
        published = _published(file.published)
        values: dict[str, object] = {
            "title": file.title or "", "episode_title": file.title or "", "episode_site_id": file.media_site_id,
            "collection_title": titles.get(file.collection_external_id, ""), "collection_author": "",
            "episode_published_date": published.strftime("%Y-%m-%d") if published else "",
            **_date_substitutions(published),
        }
        extension = PurePosixPath(file.path).suffix.removeprefix(".")
        try:
            rendered = prepared.render(
                values, custom_index_resolver=lambda key, _group=(), file=file: file.custom_index_values.get(key, 1),
            )
            rendered = _sanitize_rendered_path(replace_output_extension(rendered, extension), mode=mode, extension=extension)
        except ValueError as exc:
            rendered = f"(could not render: {exc})"
        if rendered == file.path:
            identical += 1
        elif len(differences) < _PROOF_DIFFERENCES:
            differences.append({"path": file.path, "rendered": rendered})
    return {"identical": identical, "total": len(adopted), "differences": differences}


def _filename_mode(plan: ImportPlan) -> FilenameRestrictionMode:
    setting = next((item for item in plan.settings if item.key == "downloads.filename_restriction_mode"), None)
    try:
        return FilenameRestrictionMode(setting.value) if setting else FilenameRestrictionMode(
            get_settings().download_settings.filename_restriction_mode,
        )
    except ValueError:
        return FilenameRestrictionMode.WINDOWS


def _selected_collections(plan: ImportPlan, options: ImportOptions) -> list[CollectionPlan]:
    if options.collections is None:
        return list(plan.collections)
    chosen = set(options.collections)
    return [collection for collection in plan.collections if collection.external_id in chosen]


def _selected_settings(plan: ImportPlan, options: ImportOptions) -> set[str]:
    supported = {item.key for item in plan.settings if item.support != "unsupported"}
    if options.settings is None:
        return supported & _DEFAULT_SETTINGS
    return supported & set(options.settings)


def _warning(warning: ImportWarning) -> dict[str, str]:
    return {"subject": warning.subject, "message": warning.message, "support": warning.support}


# ---------- Preview ----------

def preview(session: Session, importer: Importer, options: ImportOptions) -> dict[str, Any]:
    """Everything the import would do, for the person to check first. Writes nothing."""
    loaded = load_plan(importer, options)
    plan = loaded.plan
    links = _links(session, importer.key)
    library = _library_collections(session)
    files_by_collection: dict[str, list[FilePlan]] = defaultdict(list)
    for file in plan.files:
        files_by_collection[file.collection_external_id].append(file)
    titles = {collection.external_id: collection.title for collection in plan.collections}
    profiles = {profile.external_id: profile for profile in plan.profiles}
    mode = _filename_mode(plan)

    collections = []
    for collection in plan.collections:
        files = files_by_collection.get(collection.external_id, [])
        kinds = Counter(file.kind for file in files)
        link = links.get(("collection", collection.external_id))
        linked = session.get(Collection, link.entity_id) if link and link.entity_id else None
        existing = linked or library.get(_normalise_url(collection.url))
        on_disk = sum(1 for file in files if file.kind == "file" and file.path and _exists(file.path))
        adopted = 0
        if existing is not None:
            adopted = session.scalar(select(func.count(MediaDownloadBase.id)).join(
                Episode, Episode.id == MediaDownloadBase.media_item_id,
            ).where(
                Episode.collection_id == existing.id,
                MediaDownloadBase.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value,
            )) or 0
        collections.append({
            "external_id": collection.external_id,
            "title": collection.title,
            "url": collection.url,
            "profile_external_id": collection.profile_external_id,
            "profile_name": profiles[collection.profile_external_id].name if collection.profile_external_id in profiles else None,
            "becomes": "linked" if linked else "in_library" if existing else "new",
            "collection_slug": existing.slug if existing else None,
            "files": kinds.get("file", 0),
            "files_on_disk": on_disk,
            "files_adopted": adopted,
            "suppressed": kinds.get("suppressed", 0),
            "missing": kinds.get("missing", 0),
            "download_profile_on": bool((collection.download_profile or {}).get("enable_profile")),
            "warnings": [_warning(warning) for warning in collection.warnings],
        })

    profile_files: dict[str, list[FilePlan]] = defaultdict(list)
    for collection in plan.collections:
        profile_files[collection.profile_external_id or ""].extend(files_by_collection.get(collection.external_id, []))
    profile_views = []
    for profile in plan.profiles:
        link = links.get(("profile", profile.external_id))
        linked = session.get(CollectionLocalMediaProfile, link.entity_id) if link and link.entity_id else None
        reused = None if linked else _matching_profile(session, profile)
        changes = None
        if linked is not None:
            _write, _hashes, found = _merge_fields(
                _profile_values(linked), _profile_wanted(profile), link, _unsupported(profile.warnings),
            )
            changes = asdict(found)
        profile_views.append({
            "external_id": profile.external_id,
            "name": profile.name,
            "becomes": "linked" if linked else "reused" if reused else "new",
            "local_media_profile_name": (linked or reused).name if (linked or reused) else None,
            "original_template": profile.original_template,
            "output_template": profile.output_template,
            "support": profile.support,
            "report": list(profile.report),
            "settings": dict(profile.settings),
            "custom_indexes": [asdict(index) for index in profile.custom_indexes],
            "warnings": [_warning(warning) for warning in profile.warnings],
            "path_proof": path_proof(profile, profile_files.get(profile.external_id, []), titles, mode),
            "changes": changes,
        })

    selected = _selected_settings(plan, options)
    settings = [{
        "key": item.key,
        "value": None if item.secret else item.value,
        "support": item.support,
        "note": item.note,
        "secret": item.secret,
        "selected": item.key in selected,
    } for item in plan.settings]

    last = session.scalar(select(ImportRun).where(ImportRun.importer == importer.key)
                          .order_by(ImportRun.id.desc()).limit(1))
    return {
        "importer": importer.key,
        "version": plan.version,
        "uploaded_at": uploaded_at(importer),
        "path_map": {"source": loaded.path_map[0], "target": loaded.path_map[1],
                     "sampled": loaded.sampled, "found": loaded.found},
        "collections": collections,
        "profiles": profile_views,
        "settings": settings,
        "warnings": [_warning(warning) for warning in plan.warnings],
        "last_run": run_summary(last) if last else None,
        "counts": {
            "collections": len(plan.collections),
            "files": sum(1 for file in plan.files if file.kind == "file"),
        },
    }


def run_summary(run: ImportRun) -> dict[str, Any]:
    return {
        "id": run.id, "status": run.status, "created_at": run.created_at, "finished_at": run.finished_at,
        "uploaded_at": run.uploaded_at, "counts": dict(run.counts or {}), "error": run.error,
    }


# ---------- Running ----------

def start_run(session: Session, importer: Importer, options: ImportOptions) -> ImportRun:
    """Record the run and queue the task that applies it."""
    from task_manager.scheduler.operation_factory import create_operation

    from backend.api.endpoints.imports.operations import ImportRunOperation

    running = session.scalar(select(ImportRun.id).where(
        ImportRun.importer == importer.key, ImportRun.status == RUNNING,
    ).limit(1))
    if running is not None:
        raise ImportServiceError("An import from this program is already running")
    stamp = uploaded_at(importer)
    if stamp is None:
        raise ImportServiceError(f"Upload {importer.name}'s config folder first")
    run = ImportRun(importer=importer.key, status=RUNNING, options=options.to_dict(), uploaded_at=stamp,
                    report=[], counts={})
    session.add(run)
    session.flush()
    create_operation(session, ImportRunOperation(run, importer_name=importer.name))
    return run


@dataclass
class _Report:
    entries: list[dict[str, Any]] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)

    def add(self, kind: str, subject: str, message: str, **extra: Any) -> None:
        self.entries.append({"kind": kind, "subject": subject, "message": message, **extra})


def _apply_setting(key: str, value: object) -> None:
    """Change one VODLoft setting the way the Settings screen does."""
    if key == "downloads.filename_restriction_mode":
        from backend.api.endpoints.settings.service import save_ui_settings
        from backend.api.models.settings import SettingsAPIUpdate, SettingsValues

        values = SettingsValues.from_app_settings(get_settings())
        values.download_settings.filename_restriction_mode = FilenameRestrictionMode(str(value))
        save_ui_settings(SettingsAPIUpdate(values=values, changed_fields=["downloadSettings.filenameRestrictionMode"]))
        return
    from sources import get_source

    source = get_source("ytdlp")
    if key == "ytdlp.youtube_api_key":
        source.save_api_key(str(value))
    elif key == "ytdlp.cookies":
        source.save_cookies(Path(str(value)).read_bytes())
    else:
        raise ImportServiceError(f"VODLoft can't apply the setting {key}")


def _current_setting(key: str) -> object:
    if key == "downloads.filename_restriction_mode":
        return str(get_settings().download_settings.filename_restriction_mode)
    return None


def _apply_settings(session: Session, plan: ImportPlan, options: ImportOptions, links, run: ImportRun, report: _Report) -> None:
    selected = _selected_settings(plan, options)
    for item in plan.settings:
        if item.support == "unsupported":
            report.add("not_supported", item.key, item.note or "Not imported yet")
            continue
        if item.key not in selected:
            continue
        link = links.get(("setting", item.key))
        current = {"value": _current_setting(item.key)}
        # A secret is never compared: it is applied when asked for, and not remembered.
        wanted = {"value": None if item.secret else item.value}
        write, hashes, changes = _merge_fields(current, wanted, link, ())
        if changes.kept:
            report.add("kept", item.key, "You changed this setting in VODLoft since the last import; it was kept")
            continue
        if not item.secret and not write:
            _remember(session, links, run.importer, "setting", item.key, 0, hashes, [], run.id)
            continue
        try:
            _apply_setting(item.key, item.value)
        except Exception as exc:  # noqa: BLE001  (a setting that fails is reported, the import goes on)
            report.add("failed", item.key, f"Could not apply: {exc}")
            continue
        _remember(session, links, run.importer, "setting", item.key, 0, hashes, [], run.id)
        report.add("setting", item.key, item.note or "Applied")
        report.counts["settings"] += 1


def _unique_name(session: Session, name: str) -> str:
    from backend.utils.helpers import slugify

    candidate, number = name, 1
    while session.scalar(select(CollectionLocalMediaProfile.id).where(
        CollectionLocalMediaProfile.slug == slugify(candidate),
    ).limit(1)) is not None:
        number += 1
        candidate = f"{name} ({number})"
    return candidate


def _upsert_profile(session: Session, plan: ProfilePlan, links, run: ImportRun, report: _Report) -> CollectionLocalMediaProfile | None:
    from fastapi import HTTPException

    from backend.api.endpoints.collection_local_media_profiles.service import (
        create_collection_local_media_profile, update_collection_local_media_profile,
    )
    from backend.api.models.collection_local_media_profile import (
        CollectionLocalMediaProfileAPICreate, CollectionLocalMediaProfileAPIUpdate,
    )

    if plan.output_template is None:
        report.add("failed", plan.name, "The output template could not be converted; its sources were not imported",
                   warnings=[_warning(warning) for warning in plan.warnings])
        return None
    link = links.get(("profile", plan.external_id))
    existing = session.get(CollectionLocalMediaProfile, link.entity_id) if link and link.entity_id else None
    unsupported = _unsupported(plan.warnings)
    wanted = _profile_wanted(plan)
    try:
        if existing is None:
            reused = _matching_profile(session, plan)
            if reused is not None:
                write, hashes, _changes = _merge_fields(_profile_values(reused), wanted, None, unsupported)
                _remember(session, links, run.importer, "profile", plan.external_id, reused.id,
                          {name: _hash(value) for name, value in _profile_values(reused).items()}, unsupported, run.id)
                report.add("reused", plan.name, f"Uses the Local Media Profile {reused.name}, which names files the same way")
                return reused
            body = CollectionLocalMediaProfileAPICreate.model_validate({
                **{name: value for name, value in wanted.items() if value is not None},
                "name": _unique_name(session, plan.name),
                "type": "collection",
            })
            created = create_collection_local_media_profile(session, body)
            profile = session.get(CollectionLocalMediaProfile, created.id)
            _write, hashes, _changes = _merge_fields(_profile_values(profile), wanted, None, unsupported)
            _remember(session, links, run.importer, "profile", plan.external_id, profile.id, hashes, unsupported, run.id)
            report.add("created", plan.name, f"Local Media Profile {profile.name}", support=plan.support,
                       warnings=[_warning(warning) for warning in plan.warnings])
            report.counts["profiles_created"] += 1
            return profile
        write, hashes, changes = _merge_fields(_profile_values(existing), wanted, link, unsupported)
        if write:
            values = {**_profile_values(existing), **write}
            body = CollectionLocalMediaProfileAPIUpdate.model_validate({
                **{name: value for name, value in values.items() if value is not None},
                "name": existing.name, "type": "collection",
            })
            update_collection_local_media_profile(session, existing.slug, body)
        _remember(session, links, run.importer, "profile", plan.external_id, existing.id, hashes, unsupported, run.id)
        _report_changes(report, existing.name, changes)
        return existing
    except HTTPException as exc:
        detail = exc.detail[0]["msg"] if isinstance(exc.detail, list) and exc.detail else str(exc.detail)
        report.add("failed", plan.name, f"{detail}; its sources were not imported")
        return None
    except ValueError as exc:
        report.add("failed", plan.name, f"{exc}; its sources were not imported")
        return None


def _report_changes(report: _Report, subject: str, changes: _Changes) -> None:
    if changes.updated:
        report.add("updated", subject, "Updated: " + ", ".join(changes.updated))
        report.counts["updated"] += 1
    if changes.kept:
        report.add("kept", subject, "Kept your change: " + ", ".join(changes.kept))
    if changes.newly_mapped:
        report.add("newly_mapped", subject, "Now imported: " + ", ".join(changes.newly_mapped))


def _create_collection(session: Session, plan: CollectionPlan) -> Collection:
    """A new yt-dlp Collection for the plan, looked up the way Add Collection does."""
    from backend.api.endpoints.collections.as_bundle.service import create_collection_bundle
    from backend.api.models.collection_as_bundle import CollectionAPICreateBundle
    from backend.utils.helpers import slugify
    from sources import get_source

    source = get_source("ytdlp")
    details = source.collection_details(plan.url)
    author = details.author_name or details.title
    payload = CollectionAPICreateBundle.model_validate({
        "collection": {
            "slug": details.slug, "sourceKey": source.id, "title": plan.title or details.title,
            "description": details.description, "sharingUrl": details.url,
            "membershipLevel": "FREE", "type": plan.settings.get("type", "series"),
            "episodeIdentifier": plan.settings.get("episode_identifier", "date_based"),
            "authorName": author, "authorSlug": slugify(author) or details.slug,
            "thumbnailLandscapePath": details.image_url,
        },
        "seasons": [],
    })
    created = create_collection_bundle(session, None, payload)
    return session.get(Collection, created.id)


def _upsert_collection(session: Session, plan: CollectionPlan, library, links, run: ImportRun, report: _Report) -> tuple[Collection | None, bool]:
    """The Collection, and whether it was just created (and so is being indexed)."""
    link = links.get(("collection", plan.external_id))
    existing = session.get(Collection, link.entity_id) if link and link.entity_id else None
    created = False
    if existing is None:
        existing = library.get(_normalise_url(plan.url))
        if existing is not None:
            report.add("linked", plan.title, f"Already in the Library as {existing.title}; linked, not added twice")
            report.counts["collections_linked"] += 1
    if existing is None:
        try:
            with session.begin_nested():
                existing = _create_collection(session, plan)
        except Exception as exc:  # noqa: BLE001  (one source that can't be looked up doesn't stop the rest)
            report.add("failed", plan.title, f"Could not add it: {exc}")
            return None, False
        created = True
        library[_normalise_url(existing.sharing_url)] = existing
        report.add("created", plan.title, "Added to the Library", warnings=[_warning(warning) for warning in plan.warnings])
        report.counts["collections_created"] += 1
    _remember(session, links, run.importer, "collection", plan.external_id, existing.id,
              link.written if link else {}, _unsupported(plan.warnings), run.id)
    return existing, created


def _upsert_download_profile(
    session: Session, plan: CollectionPlan, collection: Collection, profile: CollectionLocalMediaProfile,
    links, run: ImportRun, report: _Report,
) -> DownloadProfile | None:
    if plan.download_profile is None:
        return None
    external_id = f"{plan.external_id}:{plan.profile_external_id}"
    link = links.get(("download_profile", external_id))
    existing = session.get(DownloadProfile, link.entity_id) if link and link.entity_id else None
    if existing is None:
        existing = session.scalar(select(DownloadProfile).where(
            DownloadProfile.collection_id == collection.id, DownloadProfile.local_media_profile_id == profile.id,
        ).limit(1))
        link = None if existing is None else link
    wanted = _download_profile_wanted(plan)
    unsupported = _unsupported(plan.warnings)
    if existing is None:
        values = dict(wanted)
        starting = values.get("download_starting_from")
        existing = DownloadProfile(
            collection_id=collection.id, local_media_profile_id=profile.id, enable_profile=False,
            download_with_countdown=False, redownload_final=False, include_upcoming_seasons=True,
            **{**values, "download_starting_from": date.fromisoformat(starting) if starting else None},
        )
        session.add(existing)
        session.flush()
        _write, hashes, _changes = _merge_fields(_download_profile_values(existing), wanted, None, unsupported)
        report.counts["download_profiles_created"] += 1
    else:
        write, hashes, changes = _merge_fields(_download_profile_values(existing), wanted, link, unsupported)
        for name, value in write.items():
            setattr(existing, name, date.fromisoformat(value) if name == "download_starting_from" and value else value)
        _report_changes(report, f"{collection.title} Download Profile", changes)
    _remember(session, links, run.importer, "download_profile", external_id, existing.id, hashes, unsupported, run.id)
    return existing


def _index_running(session: Session, collection_id: int) -> bool:
    from backend.services.existing_files import _index_running as running

    return running(session, collection_id)


def apply_run(session: Session, run_id: int) -> dict[str, int]:
    """Apply a run's plan: settings, profiles, Collections, Download Profiles, then the files."""
    run = session.get(ImportRun, run_id)
    if run is None:
        return {}
    importer = get_importer(run.importer)
    options = ImportOptions.from_dict(run.options or {})
    report = _Report()
    try:
        loaded = load_plan(importer, options)
    except (UploadError, ValueError, OSError) as exc:
        run.status, run.error, run.finished_at = FAILED, str(exc), datetime.now(timezone.utc)
        session.commit()
        raise
    plan = loaded.plan
    run.version = plan.version
    links = _links(session, importer.key)
    for warning in plan.warnings:
        report.add("warning", warning.subject, warning.message)

    _apply_settings(session, plan, options, links, run, report)
    session.flush()

    selected = _selected_collections(plan, options)
    profile_plans = {profile.external_id: profile for profile in plan.profiles}
    needed = {collection.profile_external_id for collection in selected}
    profiles: dict[str, CollectionLocalMediaProfile | None] = {}
    for external_id in sorted(needed, key=lambda key: (key.count(":"), key)):
        if external_id in profile_plans:
            profiles[external_id] = _upsert_profile(session, profile_plans[external_id], links, run, report)
    session.flush()

    files_by_collection: dict[str, list[FilePlan]] = defaultdict(list)
    for file in plan.files:
        files_by_collection[file.collection_external_id].append(file)
    library = _library_collections(session)
    steps: list[ImportStep] = []
    for collection_plan in selected:
        profile = profiles.get(collection_plan.profile_external_id or "")
        if profile is None:
            continue
        collection, created = _upsert_collection(session, collection_plan, library, links, run, report)
        if collection is None:
            continue
        download_profile = _upsert_download_profile(session, collection_plan, collection, profile, links, run, report)
        enable = bool(options.enable_download_profiles and (collection_plan.download_profile or {}).get("enable_profile"))
        if download_profile is not None and download_profile.enable_profile:
            # Already on (by the person, or an earlier run): hold it until the files are adopted.
            enable = True
            download_profile.enable_profile = False
        step = ImportStep(
            run_id=run.id, collection_id=collection.id, local_media_profile_id=profile.id,
            download_profile_id=download_profile.id if download_profile else None,
            enable_download_profile=enable, status=STEP_WAITING,
            files=[asdict(file) for file in files_by_collection.get(collection_plan.external_id, [])],
            result={},
        )
        session.add(step)
        steps.append(step)
        session.flush()
        if not created:
            known = set(session.scalars(select(Episode.source_slug).where(Episode.collection_id == collection.id)))
            missing = {file["media_site_id"] for file in step.files} - known
            if missing and not _index_running(session, collection.id):
                from task_manager.scheduler.operation_factory import create_operation

                from backend.api.endpoints.collections.operations import CollectionSyncOperation

                create_operation(session, CollectionSyncOperation(collection))
            elif not missing and not _index_running(session, collection.id):
                _queue_step(session, step)
    run.report = report.entries
    run.counts = dict(report.counts)
    run.status = WAITING if steps else FINISHED
    if not steps:
        run.finished_at = datetime.now(timezone.utc)
    session.commit()
    if any(item.key == "ytdlp.cookies" for item in plan.settings):
        remove_secrets(importer)
    return dict(report.counts)


def _queue_step(session: Session, step: ImportStep) -> None:
    from task_manager.scheduler.operation_factory import create_operation

    from backend.api.endpoints.imports.operations import ImportStepOperation

    collection = session.get(Collection, step.collection_id)
    create_operation(session, ImportStepOperation(collection, step_id=step.id))


def start_waiting_import_steps(session: Session, collection: Collection) -> int:
    """After an index: adopt the files of every import that waited for the Collection's episodes."""
    started = 0
    for step in session.scalars(select(ImportStep).where(
        ImportStep.collection_id == collection.id, ImportStep.status == STEP_WAITING,
    )):
        _queue_step(session, step)
        started += 1
    return started


def _seed_indexes(session: Session, step: ImportStep, profile: CollectionLocalMediaProfile, episodes: dict[str, Episode]) -> int:
    """Give the imported episodes the numbers the other program gave them, before any file is adopted.

    Episodes the import has no number for lose theirs, so they are numbered
    after the highest imported one and never repeat an imported number.
    """
    keys = {definition.key for definition in get_indexing_value_definitions(profile) if definition.keep_numbers}
    seeded = 0
    numbered: dict[int, dict[str, int]] = {}
    for file in step.files:
        episode = episodes.get(file["media_site_id"])
        values = {key: value for key, value in (file.get("custom_index_values") or {}).items() if key in keys}
        if episode is not None and values:
            numbered[episode.id] = values
    if not numbered:
        return 0
    prefix = f"{INDEX_ASSIGNMENT_PREFIX}{profile.id}."
    for episode in episodes.values():
        if episode.id in numbered:
            for key, value in numbered[episode.id].items():
                set_episode_index_assignment(episode, profile.id, key, value)
                seeded += 1
        elif any(item.key.startswith(prefix) for item in episode.meta_items):
            remove_episode_index_assignments(episode, profile.id, keys=keys)
    session.flush()
    from backend.services.custom_indexes import request_custom_index_reconciliation

    request_custom_index_reconciliation(session, collection_id=step.collection_id, local_media_profile_id=profile.id)
    return seeded


def _suppress(session: Session, episode: Episode, profile: CollectionLocalMediaProfile) -> bool:
    existing = session.scalar(select(MediaDownloadBase).where(
        MediaDownloadBase.media_item_id == episode.id, MediaDownloadBase.local_media_profile_id == profile.id,
    ))
    if existing is not None:
        if existing.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value:
            return False
        existing.automatic_retry_suppressed = True
        return True
    session.add(EpisodeMediaDownload(
        type="episode", media_item_id=episode.id, local_media_profile_id=profile.id, file_path="",
        artifact_status=MediaDownloadArtifactStatus.ABSENT.value, automatic_retry_suppressed=True,
    ))
    return True


def run_step(session: Session, step_id: int) -> dict[str, int]:
    """Number, adopt and hold back the episodes of one imported Collection."""
    step = session.get(ImportStep, step_id)
    if step is None or step.status != STEP_WAITING:
        return {}
    profile = session.get(CollectionLocalMediaProfile, step.local_media_profile_id)
    run = session.get(ImportRun, step.run_id)
    episodes = {
        episode.source_slug: episode
        for episode in session.scalars(select(Episode).where(Episode.collection_id == step.collection_id))
        if episode.source_slug
    }
    counts: Counter = Counter()
    counts["numbers"] = _seed_indexes(session, step, profile, episodes)
    problems: list[dict[str, str]] = []
    for file in step.files:
        episode = episodes.get(file["media_site_id"])
        if episode is None:
            if file["kind"] == "file":
                counts["not_indexed"] += 1
                if len(problems) < 50:
                    problems.append({"path": file["path"], "error": "The video is not in the Collection (removed or private)"})
            continue
        if file["kind"] == "suppressed":
            counts["suppressed"] += int(_suppress(session, episode, profile))
            continue
        if file["kind"] != "file":
            continue
        try:
            with session.begin_nested():
                adopted = adopt(session, media=episode, local_media_profile=profile, path=real_path(file["path"]),
                                matched_by="Recorded path", metadata={"importer": run.importer if run else None})
        except (AdoptionError, OSError, ValueError) as exc:
            counts["not_adopted"] += 1
            if len(problems) < 50:
                problems.append({"path": file["path"], "error": str(exc)})
            continue
        counts["adopted" if adopted.created else "already_adopted"] += 1
    if step.download_profile_id is not None:
        download_profile = session.get(DownloadProfile, step.download_profile_id)
        if download_profile is not None:
            counts["would_download"] = _would_download(session, download_profile)
            if step.enable_download_profile:
                download_profile.enable_profile = True
                queue_event(session, "download_profile.updated", {
                    "resource_id": download_profile.id, "id": download_profile.id,
                    "collection_id": download_profile.collection_id,
                })
    step.result = {"counts": dict(counts), "problems": problems}
    step.status = STEP_DONE
    session.flush()
    _finish_run_if_done(session, step.run_id)
    session.commit()
    return dict(counts)


def _would_download(session: Session, profile: DownloadProfile) -> int:
    """What the Download Profile's first sweep would download: its episodes that have no file."""
    from task_manager.tasks.workers.download_profile_worker._helpers import get_download_profile_episodes

    wanted = {episode.id for episode in get_download_profile_episodes(session, profile)}
    if not wanted:
        return 0
    have = set(session.scalars(select(MediaDownloadBase.media_item_id).where(
        MediaDownloadBase.media_item_id.in_(wanted),
        MediaDownloadBase.local_media_profile_id == profile.local_media_profile_id,
        (MediaDownloadBase.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value)
        | MediaDownloadBase.automatic_retry_suppressed.is_(True),
    )))
    return len(wanted - have)


def _finish_run_if_done(session: Session, run_id: int) -> None:
    run = session.get(ImportRun, run_id)
    if run is None or run.status != WAITING:
        return
    steps = list(session.scalars(select(ImportStep).where(ImportStep.run_id == run_id)))
    if any(step.status == STEP_WAITING for step in steps):
        return
    counts = Counter(run.counts or {})
    for step in steps:
        counts.update((step.result or {}).get("counts", {}))
    run.counts = dict(counts)
    run.status = FINISHED
    run.finished_at = datetime.now(timezone.utc)


def run_view(session: Session, run: ImportRun) -> dict[str, Any]:
    """A run with its report and what happened to each Collection's files."""
    steps = []
    for step in session.scalars(select(ImportStep).where(ImportStep.run_id == run.id).order_by(ImportStep.id)):
        collection = session.get(Collection, step.collection_id)
        steps.append({
            "collection_slug": collection.slug if collection else None,
            "collection_title": collection.title if collection else None,
            "status": step.status,
            "files": sum(1 for file in step.files if file.get("kind") == "file"),
            "counts": (step.result or {}).get("counts", {}),
            "problems": (step.result or {}).get("problems", []),
            "download_profile_on": step.enable_download_profile and step.status == STEP_DONE,
        })
    return {**run_summary(run), "options": run.options, "version": run.version, "report": run.report, "steps": steps}
