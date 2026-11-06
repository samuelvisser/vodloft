"""Matching files already on disk to a Collection's episodes, and adopting them.

A scan belongs to one Collection and Local Media Profile. It waits for the
Collection's first index, reads the folder, matches each media file with the
evidence in ``importer.existing_files`` and keeps the result until a person
adopts the matches. Download Profiles held for the scan are switched on when
the scan is finished, so they only see the episodes that still have no file.
"""
from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any

from jinja2 import Environment, TemplateSyntaxError, nodes
from jinja_analysis import analyze_template
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import (
    Collection,
    DownloadProfile,
    Episode,
    ExistingFileScan,
    LocalMediaProfileBase,
    MediaDownloadBase,
)
from backend.services.adoption import AdoptionError, adopt, download_root, real_path, virtual_path
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.utils.custom_index import CustomIndexNotReadyError
from backend.utils.output_template import episode_output_template_values, resolve_episode_output_path
from importer.existing_files import EpisodeFacts, match_files, scan_folder, template_patterns
from task_manager.events.transactional import queue_event
from task_manager.scheduler.db import TaskOperation

WAITING, SCANNING, READY, FAILED, FINISHED = "waiting", "scanning", "ready", "failed", "finished"
SCAN_TASK_KEY = "scan_existing_files"
_INDEX_OPERATION_KINDS = ("collection.index", "collection.sync")
_ACTIVE = ("QUEUED", "RUNNING", "WAITING")
_SIDECAR_LIMIT = 4 * 1024 * 1024
_FOLDER_SAMPLE = 20
_KINDS = ("adopted", "certain", "likely", "review", "unmatched")
_EVIDENCE_NAMES = {
    "recorded": "Recorded path", "expected_path": "Expected path", "id_in_name": "Id in name",
    "sidecar": "Sidecar", "template": "Template", "title_date": "Title and date",
}


class ExistingFilesError(ValueError):
    pass


def default_folder(output_template: str) -> str:
    """The deepest folder every path of the template starts with, as a /downloads/ path.

    The template is read the way it renders, so a ``{% set %}`` line at its start or a
    branch that writes the same folder doesn't hide the folder after it.
    """
    try:
        analysis = analyze_template(output_template, environment=Environment(), max_variants=32)
    except TemplateSyntaxError:
        return "/downloads"
    starts = []
    for variant in analysis.variants:
        text = ""
        for part in variant.parts:
            if isinstance(part, nodes.Const) and isinstance(part.value, str):
                part = part.value
            if not isinstance(part, str):
                break
            text += part
        starts.append(text)
    fixed = os.path.commonprefix(starts) if starts else ""
    folder = fixed[: fixed.rfind("/")] if "/" in fixed else ""
    return folder if folder.startswith("/downloads") else "/downloads"


def collection_folder(collection: Collection, profile: LocalMediaProfileBase) -> str | None:
    """The Collection's own folder in this profile, as a /downloads/ path.

    It is the folder the profile puts the show's artwork in, so the same folder
    decides which files belong to the Collection. None when the template has no
    folder of its own for each Collection.
    """
    from backend.services.collection_assets import resolve_collection_media_directory

    try:
        root = resolve_collection_media_directory(collection, profile.output_template)
        return virtual_path(Path(root.path)) if root.path else None
    except (AdoptionError, OSError, ValueError):
        return None


def scan_folder_for(collection: Collection, profile: LocalMediaProfileBase) -> str:
    """The folder to look in for a Collection's files: its own folder when there is one, else the profile's."""
    own = collection_folder(collection, profile)
    try:
        if own is not None and real_path(own + "/").is_dir():
            return own
    except AdoptionError:
        pass
    return default_folder(profile.output_template)


def check_folder(folder: str) -> Path:
    folder = folder.strip().rstrip("/") or "/downloads"
    path = real_path(folder + "/") if folder != "/downloads" else download_root()
    if not path.is_dir():
        raise ExistingFilesError(f"{folder} is not a folder VODLoft can see")
    return path


def list_folders(folder: str) -> dict[str, Any]:
    """The folders inside one /downloads/ folder, for the folder picker."""
    path = check_folder(folder)
    try:
        names = sorted(
            entry.name for entry in path.iterdir()
            if entry.is_dir() and not entry.name.startswith(".")
        )
    except OSError as exc:
        raise ExistingFilesError(f"VODLoft can't read {folder}: {exc.strerror}") from exc
    current = virtual_path(path)
    return {"folder": current, "parent": None if current == "/downloads/" else virtual_path(path.parent), "folders": names}


def _index_running(session: Session, collection_id: int) -> bool:
    return session.scalar(
        select(TaskOperation.id).where(
            TaskOperation.kind.in_(_INDEX_OPERATION_KINDS),
            TaskOperation.resource_type == "collection",
            TaskOperation.resource_id == collection_id,
            TaskOperation.status.in_(_ACTIVE),
        ).limit(1)
    ) is not None


def request_scan(
    session: Session,
    collection: Collection,
    local_media_profile: LocalMediaProfileBase,
    *,
    folder: str,
    template: str | None = None,
    hold: Sequence[DownloadProfile] = (),
    wait_for_index: bool = False,
    indexed: bool = False,
) -> ExistingFileScan:
    """Start (or restart) the scan for this Collection and profile.

    ``hold`` switches those Download Profiles off until the scan is finished.
    ``indexed`` says the episodes are in already, so an index still finishing doesn't make it wait.
    """
    folder = folder.strip().rstrip("/") or "/downloads"
    if not folder.startswith("/downloads"):
        raise ExistingFilesError("The folder must be inside /downloads/")
    if template is not None and template.strip() and not template_patterns(template.strip()):
        raise ExistingFilesError("That template reads no value out of a file name")
    scan = session.scalar(select(ExistingFileScan).where(
        ExistingFileScan.collection_id == collection.id,
        ExistingFileScan.local_media_profile_id == local_media_profile.id,
    ))
    held = [profile.id for profile in hold if profile.enable_profile]
    for profile in hold:
        profile.enable_profile = False
    if scan is None:
        scan = ExistingFileScan(collection_id=collection.id, local_media_profile_id=local_media_profile.id,
                                folder=folder, status=WAITING, results=[], held_download_profile_ids=[])
        session.add(scan)
    scan.folder = folder
    scan.template = template.strip() if template and template.strip() else None
    scan.error = None
    scan.results = []
    scan.held_download_profile_ids = sorted({*scan.held_download_profile_ids, *held})
    waiting = wait_for_index or (not indexed and _index_running(session, collection.id))
    scan.status = WAITING if waiting else SCANNING
    session.flush()
    if not waiting:
        queue_scan(session, collection, local_media_profile)
    return scan


def scan_profile(session: Session, profile: LocalMediaProfileBase) -> int:
    """Look for existing files for every Collection that downloads with this profile, each in its own folder."""
    collections = session.scalars(select(Collection).where(Collection.id.in_(
        select(DownloadProfile.collection_id).where(
            DownloadProfile.local_media_profile_id == profile.id, DownloadProfile.collection_id.is_not(None),
        )
    )).order_by(Collection.title)).all()
    for collection in collections:
        request_scan(session, collection, profile, folder=scan_folder_for(collection, profile))
    return len(collections)


def queue_scan(session: Session, collection: Collection, local_media_profile: LocalMediaProfileBase) -> None:
    from task_manager.scheduler.operation_factory import create_operation
    from task_manager.scheduler.operations import queue_operation_target_dispatch

    from backend.operations.collections import CollectionExistingFilesScanOperation

    operation = create_operation(session, CollectionExistingFilesScanOperation(
        collection, local_media_profile_id=local_media_profile.id,
    ))
    queue_operation_target_dispatch(session, operation.id, operation.targets[0].slot_key)


def _episode_facts(session: Session, collection: Collection, profile: LocalMediaProfileBase) -> list[EpisodeFacts]:
    have_file = set(session.scalars(select(MediaDownloadBase.media_item_id).where(
        MediaDownloadBase.local_media_profile_id == profile.id,
        MediaDownloadBase.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value,
    )))
    facts: list[EpisodeFacts] = []
    for episode in session.scalars(select(Episode).where(Episode.collection_id == collection.id)):
        if episode.id in have_file:
            continue
        values = episode_output_template_values(episode)
        expected: str | None = None
        try:
            path = resolve_episode_output_path(profile.output_template, episode=episode, local_media_profile=profile)
            expected = virtual_path(path).removesuffix(".ext")
        except (CustomIndexNotReadyError, ValueError, OSError):
            expected = None
        published = episode.published_date
        facts.append(EpisodeFacts(
            id=episode.id,
            title=episode.title,
            site_id=episode.source_slug or None,
            date=published.date() if published else None,
            urls=tuple(url for url in (episode.sharing_url,) if url),
            expected_path=expected,
            values=values,
        ))
    return facts


def _read_sidecar(virtual: str) -> bytes | None:
    try:
        path = real_path(virtual)
        with path.open("rb") as file:
            return file.read(_SIDECAR_LIMIT)
    except (OSError, AdoptionError):
        return None


def run_scan(session: Session, *, collection_id: int, local_media_profile_id: int) -> dict[str, int]:
    scan = session.scalar(select(ExistingFileScan).where(
        ExistingFileScan.collection_id == collection_id,
        ExistingFileScan.local_media_profile_id == local_media_profile_id,
    ))
    collection = session.get(Collection, collection_id)
    profile = session.get(LocalMediaProfileBase, local_media_profile_id)
    if scan is None or collection is None or profile is None:
        return {"files": 0}
    scan.status = SCANNING
    session.commit()
    try:
        root = check_folder(scan.folder)
        known = {
            Path(path).resolve() for path in session.scalars(select(MediaDownloadBase.file_path).where(
                MediaDownloadBase.artifact_status != MediaDownloadArtifactStatus.ABSENT.value,
            ))
        }
        episodes = _episode_facts(session, collection, profile)
        patterns = template_patterns(profile.output_template)
        if scan.template:
            patterns += template_patterns(scan.template)
        folder = virtual_path(root)
        session.rollback()
        files = [file for file in scan_folder(root) if (root / file.path).resolve() not in known]
        result = match_files(files, episodes, folder=folder, patterns=patterns, read=_read_sidecar)
    except Exception as exc:
        session.rollback()
        scan = session.get(ExistingFileScan, scan.id)
        scan.status, scan.error = FAILED, str(exc)
        session.commit()
        raise
    scan = session.get(ExistingFileScan, scan.id)
    scan.results = [{**asdict(item), "candidates": list(item.candidates), "adopted": False} for item in result.files]
    scan.status = READY
    session.commit()
    return {
        "files": len(result.files), "certain": result.count("certain"),
        "likely": result.count("likely"), "review": result.count("review"),
    }


def start_waiting_scans(session: Session, collection: Collection) -> int:
    """After an index: start every scan that waited for the Collection's episodes."""
    started = 0
    for scan in session.scalars(select(ExistingFileScan).where(
        ExistingFileScan.collection_id == collection.id, ExistingFileScan.status == WAITING,
    )):
        profile = session.get(LocalMediaProfileBase, scan.local_media_profile_id)
        if profile is None:
            continue
        scan.status = SCANNING
        queue_scan(session, collection, profile)
        started += 1
    return started


def _collection_folders(session: Session, scan: ExistingFileScan, collection: Collection) -> list[str]:
    """The folders that hold this Collection's files, as /downloads/ paths.

    Several Collections can share one Local Media Profile folder, so the files
    outside these folders belong to someone else. That is the Collection's own
    folder, the one its show artwork goes in. A template without one falls back to
    where the Collection's matches and downloads are, and where a few of its
    episodes would be saved.
    """
    profile = session.get(LocalMediaProfileBase, scan.local_media_profile_id)
    own = collection_folder(collection, profile) if profile is not None else None
    if own is not None:
        return [own]
    folders = {str(PurePosixPath(item["path"]).parent) for item in scan.results if item.get("episode_id")}
    profile = session.get(LocalMediaProfileBase, scan.local_media_profile_id)
    downloads = session.scalars(select(MediaDownloadBase.file_path).join(
        Episode, Episode.id == MediaDownloadBase.media_item_id,
    ).where(
        Episode.collection_id == collection.id,
        MediaDownloadBase.local_media_profile_id == scan.local_media_profile_id,
        MediaDownloadBase.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value,
    ).limit(_FOLDER_SAMPLE))
    expected = []
    if profile is not None:
        for episode in session.scalars(select(Episode).where(Episode.collection_id == collection.id)
                                       .order_by(Episode.published_date.desc()).limit(_FOLDER_SAMPLE)):
            try:
                expected.append(resolve_episode_output_path(
                    profile.output_template, episode=episode, local_media_profile=profile,
                ))
            except (CustomIndexNotReadyError, ValueError, OSError):
                continue
    for path in [*downloads, *expected]:
        try:
            folders.add(str(PurePosixPath(virtual_path(Path(path))).parent))
        except (AdoptionError, OSError, ValueError):
            continue
    if not folders:
        return []
    root = (scan.folder or "/downloads").rstrip("/")
    common = os.path.commonpath(sorted(folders))
    # One folder for the whole Collection, unless its files only meet in the shared folder itself.
    return [common] if common.startswith(root + "/") else sorted(folders)


def scan_view(session: Session, scan: ExistingFileScan, *, whole_folder: bool = False) -> dict[str, Any]:
    """The scan with the titles and dates of the episodes it names, for the matching screen.

    Files that match none of the Collection's episodes are only listed when they are in
    the Collection's own folders, unless ``whole_folder`` asks for every file the scan read.
    """
    collection = session.get(Collection, scan.collection_id)
    results = scan.results
    if not whole_folder and any(not item.get("episode_id") for item in results):
        folders = tuple(folder + "/" for folder in _collection_folders(session, scan, collection))
        results = [item for item in results if item.get("episode_id") or item["path"].startswith(folders)]
    ids = {item["episode_id"] for item in results if item.get("episode_id")}
    ids |= {candidate for item in results for candidate in item.get("candidates", ())}
    episodes = {
        episode.id: episode
        for episode in session.scalars(select(Episode).where(Episode.id.in_(ids)))
    } if ids else {}
    total = session.scalar(
        select(func.count(Episode.id)).where(Episode.collection_id == scan.collection_id)
    ) or 0
    with_file = session.scalar(
        select(func.count(MediaDownloadBase.id)).join(
            Episode, Episode.id == MediaDownloadBase.media_item_id,
        ).where(
            Episode.collection_id == scan.collection_id,
            MediaDownloadBase.local_media_profile_id == scan.local_media_profile_id,
            MediaDownloadBase.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value,
        )
    ) or 0
    matched = {
        item["episode_id"] for item in results
        if item.get("episode_id") and item.get("confidence") in ("certain", "likely") and not item.get("adopted")
    }
    counts = {key: 0 for key in _KINDS}
    for item in results:
        counts[_kind(item)] += 1

    def episode(episode_id: int | None) -> dict[str, Any] | None:
        found = episodes.get(episode_id) if episode_id else None
        if found is None:
            return None
        return {
            "id": found.id, "slug": found.slug, "title": found.title,
            "date": found.published_date.date().isoformat() if found.published_date else None,
            "collection_slug": collection.slug, "collection_title": collection.title,
        }

    return {
        "status": scan.status,
        "error": scan.error,
        "folder": scan.folder,
        "template": scan.template,
        "local_media_profile_id": scan.local_media_profile_id,
        "held_download_profiles": len(scan.held_download_profile_ids),
        "counts": counts,
        "episodes_without_file": max(0, total - with_file - len(matched)),
        "files": [
            {
                "path": item["path"],
                "size": item["size"],
                "episode": episode(item.get("episode_id")),
                "matched_by": _EVIDENCE_NAMES.get(item.get("evidence") or ""),
                "confidence": item.get("confidence"),
                "candidates": [view for view in (episode(candidate) for candidate in item.get("candidates", ())) if view],
                "note": item.get("note"),
                "adopted": bool(item.get("adopted")),
            }
            for item in results
        ],
    }


def _kind(file: dict[str, Any]) -> str:
    return "adopted" if file.get("adopted") else file.get("confidence") or "unmatched"


def profile_review(session: Session, profile: LocalMediaProfileBase) -> dict[str, Any]:
    """Every open scan of one Local Media Profile as one review of its whole folder.

    A file several Collections' scans read is listed once, with its best match; the
    episodes the other scans offered for it stay as candidates.
    """
    rows = session.execute(
        select(ExistingFileScan, Collection).join(Collection, Collection.id == ExistingFileScan.collection_id)
        .where(ExistingFileScan.local_media_profile_id == profile.id, ExistingFileScan.status != FINISHED)
        .order_by(Collection.title)
    ).all()
    files: dict[str, dict[str, Any]] = {}
    offered: dict[str, dict[int, dict[str, Any]]] = {}
    without_file = held = 0
    for scan, _collection in rows:
        if scan.status != READY:
            continue
        view = scan_view(session, scan, whole_folder=True)
        without_file += view["episodes_without_file"]
        held += view["held_download_profiles"]
        for file in view["files"]:
            choices = offered.setdefault(file["path"], {})
            for candidate in [file["episode"], *file["candidates"]]:
                if candidate is not None:
                    choices.setdefault(candidate["id"], candidate)
            current = files.get(file["path"])
            if current is None or _KINDS.index(_kind(file)) < _KINDS.index(_kind(current)):
                files[file["path"]] = file
    for path, file in files.items():
        mine = file["episode"]["id"] if file["episode"] else None
        file["candidates"] = [episode for id_, episode in offered[path].items() if id_ != mine]
    counts = {key: 0 for key in _KINDS}
    for file in files.values():
        counts[_kind(file)] += 1
    statuses = {scan.status for scan, _collection in rows}
    return {
        "status": next((status for status in (READY, SCANNING, WAITING, FAILED) if status in statuses), FINISHED),
        "folder": default_folder(profile.output_template),
        "local_media_profile_id": profile.id,
        "held_download_profiles": held,
        "counts": counts,
        "episodes_without_file": without_file,
        "files": sorted(files.values(), key=lambda file: file["path"]),
        "collections": [
            {"collection_slug": collection.slug, "collection_title": collection.title, "status": scan.status}
            for scan, collection in rows
        ],
    }


def adopt_matches(
    session: Session, scan: ExistingFileScan, matches: Iterable[tuple[str, int]],
) -> dict[str, Any]:
    """Adopt each ``(path, episode id)``; a path must be one the scan found."""
    profile = session.get(LocalMediaProfileBase, scan.local_media_profile_id)
    by_path = {item["path"]: index for index, item in enumerate(scan.results)}
    results = [dict(item) for item in scan.results]
    adopted = 0
    errors: list[dict[str, str]] = []
    for path, episode_id in matches:
        index = by_path.get(path)
        episode = session.get(Episode, episode_id)
        if index is None or episode is None or episode.collection_id != scan.collection_id:
            errors.append({"path": path, "error": "This file or episode is not part of the scan"})
            continue
        item = results[index]
        try:
            with session.begin_nested():
                adopt(
                    session, media=episode, local_media_profile=profile, path=real_path(path),
                    matched_by=_EVIDENCE_NAMES.get(item.get("evidence") or "", "Picked by hand")
                    if item.get("episode_id") == episode_id else "Picked by hand",
                )
        except (AdoptionError, OSError, ValueError) as exc:
            errors.append({"path": path, "error": str(exc)})
            continue
        item.update({"adopted": True, "episode_id": episode_id, "confidence": item.get("confidence") or "review"})
        adopted += 1
    scan.results = results
    session.flush()
    return {"adopted": adopted, "errors": errors}


def finish_scan(session: Session, scan: ExistingFileScan) -> int:
    """Switch the held Download Profiles back on; they now only see episodes without a file."""
    enabled = 0
    for profile_id in scan.held_download_profile_ids:
        profile = session.get(DownloadProfile, profile_id)
        if profile is None:
            continue
        profile.enable_profile = True
        enabled += 1
        queue_event(session, "download_profile.updated", {
            "resource_id": profile.id, "id": profile.id, "collection_id": profile.collection_id,
        })
    scan.held_download_profile_ids = []
    scan.status = FINISHED
    from backend.services.imports import rename_after_matching

    rename_after_matching(session, scan)
    session.flush()
    return enabled
