"""Generic Add URL, library, acquisition and local playback prototype."""

import logging
import errno
import hashlib
import json
import filecmp
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone, timedelta
from contextlib import nullcontext
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from backend.db import get_session
from backend.db.models.vodloft import (
    AcquisitionJob, Artifact, ArtifactPlacement, CollectionDownloadProfile, CollectionEntry, CollectionScan, CollectionStreamProfile, LiveAdmission, Domain, FeedSubscription, FileFinalization, LegacyMediaLink, LibraryRequest, MediaDemand, MediaSuppression, MediaItem, MediaServerExport, MovieExtraParent, PlaybackProgress, PublishedEntry, SourceConnection, SourceDomain, SourceReference, SourceSnapshot,
)
from backend.db.models.local_media_profile import DomainLocalMediaProfile
from backend.api.endpoints.vodloft.profiles import output_path_from_spec, template_values
from backend.source_manager.gateway import SourceGateway, SourceInvocationError, cancel_running_job, clear_canceled_job, validate_public_url
from backend.source_manager.runtime import command_for
from backend.services import vodloft_finalization
from backend.source_manager import runtime as source_runtime
from backend.api.endpoints.vodloft.connections import source_options
from backend.security.permissions import principal, require_connection
from config import get_settings
from source_contracts import MediaSnapshot, NormalizedSnapshot, SourceMediaReference, RepresentationPolicy
from task_manager.scheduler.db import TaskOperation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vodloft", tags=["VodLoft library"])
_download_slots = threading.BoundedSemaphore(5)
_source_slots: dict[str, threading.BoundedSemaphore] = {}
_domain_slots: dict[int, threading.BoundedSemaphore] = {}
_connection_slots: dict[int, threading.BoundedSemaphore] = {}
_source_slots_lock = threading.Lock()
_MISSING = object()
_JOB_PROGRESS = {"queued": 0, "resolving": 10, "downloading": 35,
                 "processing": 65, "verifying": 75, "finalizing": 90,
                 "available": 100, "failed": 100, "canceled": 100}


def _sync_operation(session, job: AcquisitionJob) -> None:
    if not job.operation_id:
        return
    operation = session.get(TaskOperation, job.operation_id)
    if not operation:
        return
    state = job.state
    operation.status = ({"available": "SUCCEEDED", "failed": "FAILED",
        "canceled": "CANCELED", "queued": "QUEUED"}.get(state, "RUNNING"))
    operation.progress = _JOB_PROGRESS.get(state, 0)
    operation.message = state.replace("_", " ").capitalize()
    operation.error = job.error if state == "failed" else None
    now = datetime.now(timezone.utc)
    if state not in {"queued", "available", "failed", "canceled"}:
        operation.started_at = operation.started_at or now
    operation.finished_at = now if state in {"available", "failed", "canceled"} else None
    if state == "available":
        operation.result = {"summary": "Download available", "data": {"item_id": job.item_id}}


def _download_progress(job_id: int, percent: float) -> None:
    """Map Source byte progress into the reserved download portion of a job."""
    with get_session() as session:
        job = session.get(AcquisitionJob, job_id)
        if not job or job.state != "downloading" or not job.operation_id:
            return
        operation = session.get(TaskOperation, job.operation_id)
        if not operation:
            return
        progress = min(64, 35 + int(percent * 0.29))
        if progress <= (operation.progress or 0):
            return
        operation.progress = progress
        operation.message = f"Downloading ({int(percent)}%)"
        session.commit()


def _progress_for(session, job: AcquisitionJob) -> int:
    operation = session.get(TaskOperation, job.operation_id) if job.operation_id else None
    return operation.progress if operation and operation.progress is not None else _JOB_PROGRESS.get(job.state, 0)


class JobCancelled(Exception):
    pass


def _source_problem(exc: Exception, fallback: str) -> HTTPException:
    if isinstance(exc, SourceInvocationError):
        status = {"authentication_required": 409, "rate_limited": 429,
                  "invalid_url": 422, "unsupported_operation": 422,
                  "unsupported_format": 409, "insufficient_disk": 503,
                  "unavailable": 503}.get(exc.code, 502)
        return HTTPException(status, str(exc),
            headers={"X-VodLoft-Source-Error": exc.code})
    return HTTPException(502, fallback)


class ResolveRequest(BaseModel):
    url: str = Field(min_length=8)
    source_id: str | None = None
    connection_id: int | None = None


class ImportRequest(BaseModel):
    snapshot: NormalizedSnapshot
    connection_id: int | None = None


class DownloadRequest(BaseModel):
    profile_id: int | None = None
    reference_id: int | None = None


class UserMetadataInput(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    kind: str | None = Field(default=None, pattern="^(video|movie|movie_extra)$")
    parent_id: int | None = None
    extra_type: str | None = Field(default=None, pattern="^(trailer|interview|behind_the_scenes|deleted_scene|featurette|other)$")


class PlaybackInput(BaseModel):
    seconds: float = Field(ge=0)
    completed: bool = False


def _domain(session, hostname: str) -> Domain:
    hostname = hostname.rstrip(".").lower().encode("idna").decode("ascii")
    domain = session.scalar(select(Domain).where(Domain.hostname == hostname))
    if not domain:
        domain = Domain(hostname=hostname, display_name=hostname)
        session.add(domain)
        session.flush()
    return domain


def _upsert(session, reference: SourceMediaReference, kind: str, title: str,
            description=_MISSING, duration=_MISSING,
            artwork_url=_MISSING, connection_id: int | None = None,
            published_at=_MISSING, capabilities=_MISSING,
            is_live=_MISSING, formats=_MISSING, normalized_metadata: dict | None = None) -> MediaItem:
    domain = _domain(session, reference.domain)
    supported = session.scalar(select(SourceDomain).where(
        SourceDomain.source_id == reference.source_id, SourceDomain.domain_id == domain.id))
    if not supported:
        session.add(SourceDomain(source_id=reference.source_id, domain_id=domain.id, support="verified"))
        session.flush()
    source = session.scalar(select(SourceReference).where(
        SourceReference.source_id == reference.source_id,
        SourceReference.domain_id == domain.id,
        SourceReference.namespace == reference.namespace,
        SourceReference.upstream_id == reference.upstream_id,
        SourceReference.connection_key == (connection_id or 0),
    ))
    if source:
        item = session.get(MediaItem, source.item_id)
        item.title = title
        if description is not _MISSING:
            item.description = description
        if duration is not _MISSING:
            item.duration = duration
        if artwork_url is not _MISSING:
            item.artwork_url = artwork_url
        if published_at is not _MISSING:
            item.published_at = published_at
        if capabilities is not _MISSING:
            item.capabilities = sorted(capabilities) if capabilities is not None else None
        if is_live is not _MISSING:
            item.is_live = is_live
        if formats is not _MISSING:
            item.formats = [format.model_dump(mode="json") for format in formats]
        source.url = reference.url
    else:
        related = session.scalar(select(SourceReference).where(
            SourceReference.source_id == reference.source_id,
            SourceReference.domain_id == domain.id,
            SourceReference.namespace == reference.namespace,
            SourceReference.upstream_id == reference.upstream_id))
        if not related:
            related = session.scalar(select(SourceReference).where(
                SourceReference.source_id == reference.source_id,
                SourceReference.domain_id == domain.id,
                SourceReference.url == reference.url))
        if related:
            item = session.get(MediaItem, related.item_id)
        else:
            item = MediaItem(domain_id=domain.id, kind=kind, title=title,
                             description=None if description is _MISSING else description,
                             duration=None if duration is _MISSING else duration,
                             artwork_url=None if artwork_url is _MISSING else artwork_url,
                             published_at=None if published_at is _MISSING else published_at,
                             capabilities=sorted(capabilities) if capabilities is not _MISSING and capabilities is not None else None,
                             is_live=None if is_live is _MISSING else is_live,
                             formats=[format.model_dump(mode="json") for format in formats] if formats is not _MISSING else None)
            session.add(item)
            session.flush()
        session.add(SourceReference(item_id=item.id, domain_id=domain.id,
            source_id=reference.source_id, namespace=reference.namespace,
            upstream_id=reference.upstream_id, url=reference.url,
            connection_id=connection_id, connection_key=connection_id or 0))
    if normalized_metadata is not None:
        item.normalized_metadata = {**(item.normalized_metadata or {}), **normalized_metadata}
    return item


def _reference_for(session, item_id: int, *, reference_id: int | None = None,
                   collection_id: int | None = None,
                   collection_reference_id: int | None = None) -> SourceReference | None:
    references = session.scalars(select(SourceReference).where(SourceReference.item_id == item_id)).all()
    eligible = []
    for reference in references:
        if reference.connection_id:
            connection = session.get(SourceConnection, reference.connection_id)
            if not connection or not connection.enabled:
                continue
        eligible.append(reference)
    if reference_id is not None:
        return next((reference for reference in eligible if reference.id == reference_id), None)
    if collection_id is not None:
        parent = _reference_for(session, collection_id, reference_id=collection_reference_id)
        if parent:
            matching = [reference for reference in eligible if
                reference.source_id == parent.source_id and
                reference.connection_id == parent.connection_id]
            if len(matching) == 1:
                return matching[0]
        return None
    return eligible[0] if len(eligible) == 1 else None


def _serialize(session, item: MediaItem) -> dict:
    domain = session.get(Domain, item.domain_id)
    artifact = next((candidate for candidate in session.scalars(select(Artifact).where(
        Artifact.item_id == item.id).order_by(Artifact.id.desc())).all()
        if Path(candidate.path).is_file()), None)
    return {"id": item.id, "kind": item.kind, "title": item.user_title or item.title,
            "domain": domain.hostname, "description": item.user_description or item.description,
            "artwork_url": item.artwork_url, "duration": item.duration,
            "published_at": item.published_at, "capabilities": item.capabilities,
            "is_live": item.is_live, "formats": item.formats or [],
            "chapters": (item.normalized_metadata or {}).get("chapters", []),
            "tracks": (item.normalized_metadata or {}).get("tracks", []),
            "author": (item.normalized_metadata or {}).get("author"),
            "movie_year": (item.normalized_metadata or {}).get("movie_year"),
            "parent_id": item.parent_id, "extra_type": item.extra_type,
            "downloaded": bool(artifact),
            "playback_type": "audio" if artifact and Path(artifact.path).suffix.lower() in {
                ".mp3", ".m4a", ".opus", ".ogg", ".wav"} else "video"}


@router.get("/sources")
def sources():
    return [manifest.model_dump() for manifest in SourceGateway().manifests()]


@router.get("/sources/domains")
def source_domains():
    gateway = SourceGateway()
    catalogues = []
    for manifest in gateway.manifests():
        if "domain_catalogue" in manifest.capabilities:
            try:
                catalogues.append({"source_id": manifest.source_id, **gateway.catalogue(manifest.source_id)})
            except Exception:
                logger.exception("Could not read the %s Domain catalogue", manifest.source_id)
    return catalogues


@router.get("/sources/{source_id}/manifest")
def source_manifest(source_id: str):
    manifest = next((m for m in SourceGateway().manifests() if m.source_id == source_id), None)
    if not manifest:
        raise HTTPException(404, "Source runtime is unavailable")
    return manifest


@router.get("/sources/{source_id}/domains")
def source_domain_page(source_id: str):
    source_manifest(source_id)
    return SourceGateway().catalogue(source_id)


@router.post("/sources/{source_id}/match")
def source_match(source_id: str, request: ResolveRequest):
    source_manifest(source_id)
    try:
        return SourceGateway().match(source_id, request.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise _source_problem(exc, "Source match operation is unavailable") from exc


@router.post("/sources/{source_id}/entries")
def source_entries(source_id: str, request: ResolveRequest, http_request: Request, cursor: str | None = None,
                   limit: int = 50):
    source_manifest(source_id)
    require_connection(http_request, request.connection_id)
    try:
        with get_session() as session:
            options = source_options(session, source_id, request.connection_id)
        return SourceGateway().entries(source_id, request.url, cursor=cursor, limit=limit,
            **options)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise _source_problem(exc, "Source enumeration is unavailable") from exc


@router.get("/sources/{source_id}/search")
def source_search(source_id: str, query: str, http_request: Request, cursor: str | None = None,
                  limit: int = 30, connection_id: int | None = None):
    manifest = source_manifest(source_id)
    if "search" not in manifest.capabilities:
        raise HTTPException(422, "This Source does not advertise search")
    require_connection(http_request, connection_id)
    try:
        with get_session() as session:
            options = source_options(session, source_id, connection_id)
        return SourceGateway().search(source_id, query, cursor=cursor,
            limit=limit, **options)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise _source_problem(exc, "Source search is unavailable") from exc


@router.get("/sources/runtimes")
def source_runtimes():
    return source_runtime.status()


class SourceUpdatePolicyInput(BaseModel):
    automatic: bool = True
    pinned_version: str | None = None
    channel: str = Field(default="stable", pattern="^(stable|beta)$")


@router.put("/sources/{source_id}/policy")
def source_update_policy(source_id: str, data: SourceUpdatePolicyInput):
    try:
        return source_runtime.set_policy(source_id, data.automatic, data.pinned_version,
            data.channel)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/sources/runtimes/check")
def check_source_updates():
    try:
        return source_runtime.check_updates(force=True)
    except (ValueError, OSError, RuntimeError) as exc:
        logger.exception("Source bundle update failed")
        raise HTTPException(422, "Source bundle verification or health check failed") from exc


@router.post("/sources/{source_id}/runtimes/{version}/activate")
def activate_source(source_id: str, version: str):
    try:
        return source_runtime.activate(source_id, version)
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(422, "Source runtime failed its compatibility check") from exc


@router.post("/sources/{source_id}/rollback")
def rollback_source(source_id: str):
    try:
        return source_runtime.rollback(source_id)
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/resolve")
def resolve(request: ResolveRequest, http_request: Request):
    require_connection(http_request, request.connection_id)
    try:
        validate_public_url(request.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    gateway = SourceGateway()
    manifests = gateway.manifests()
    candidates = [request.source_id] if request.source_id else [s.source_id for s in manifests]
    if not candidates:
        raise HTTPException(503, "No healthy Source runtime is installed")
    if request.source_id and request.source_id not in {m.source_id for m in manifests}:
        raise HTTPException(422, "The selected Source runtime is unavailable")
    if request.connection_id:
        with get_session() as session:
            connection = session.get(SourceConnection, request.connection_id)
            if not connection or not connection.enabled:
                raise HTTPException(422, "The selected Source connection is unavailable")
            if request.source_id and request.source_id != connection.source_id:
                raise HTTPException(422, "Source and connection do not match")
            candidates = [connection.source_id]
    if not request.source_id and not request.connection_id:
        matches = []
        for source_id in candidates:
            try:
                score = gateway.match(source_id, request.url).confidence
            except Exception:
                score = 1  # Older contract-compatible Sources can still resolve URLs.
            if score:
                matches.append((score, source_id))
        candidates = [source_id for _, source_id in sorted(matches, reverse=True)]
    if not candidates:
        raise HTTPException(422, "No installed Source recognizes this URL")
    source_id = candidates[0]
    try:
        with get_session() as session:
            options = source_options(session, source_id, request.connection_id)
        return gateway.resolve(source_id, request.url, **options)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.info("Source %s could not resolve URL", source_id, exc_info=True)
        raise _source_problem(exc,
            f"{source_id} could not resolve this URL; choose another Source explicitly if appropriate") from exc


@router.post("/import")
def import_media(request: ImportRequest, http_request: Request):
    require_connection(http_request, request.connection_id)
    snapshot = request.snapshot
    # Re-resolve the original URL instead of trusting client-supplied metadata or identity.
    try:
        with get_session() as session:
            options = source_options(session, snapshot.reference.source_id, request.connection_id)
        snapshot = SourceGateway().resolve(snapshot.reference.source_id, snapshot.reference.url, **options)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise _source_problem(exc, "Source could not verify this media") from exc
    return _import_snapshot(snapshot, request.connection_id)


def _import_snapshot(snapshot: MediaSnapshot, connection_id: int | None = None,
                     *, scan_error: str | None = None, next_cursor: str | None = None,
                     runtime_version: str | None = None) -> dict:
    with get_session() as session:
        item = _upsert(session, snapshot.reference, snapshot.kind, snapshot.title,
                       snapshot.description if "description" in snapshot.model_fields_set else _MISSING,
                       snapshot.duration if "duration" in snapshot.model_fields_set else _MISSING,
                       snapshot.artwork_url if "artwork_url" in snapshot.model_fields_set else _MISSING,
                       connection_id,
                       published_at=snapshot.published_at if "published_at" in snapshot.model_fields_set else _MISSING,
                       capabilities=snapshot.capabilities if "capabilities" in snapshot.model_fields_set else _MISSING,
                       is_live=snapshot.is_live if "is_live" in snapshot.model_fields_set else _MISSING,
                       formats=snapshot.formats if "formats" in snapshot.model_fields_set else _MISSING,
                       normalized_metadata=snapshot.model_dump(mode="json", include={
                           "artwork", "chapters", "tracks", "author", "movie_year"}, exclude_unset=True))
        session.flush()
        metadata_snapshot = snapshot.model_dump(mode="json", exclude={"reference", "entries", "extras"},
                                                exclude_unset=True)
        previous = session.scalar(select(SourceSnapshot).where(
            SourceSnapshot.item_id == item.id,
            SourceSnapshot.source_id == snapshot.reference.source_id,
            SourceSnapshot.connection_id == connection_id).order_by(SourceSnapshot.id.desc()))
        if not previous or previous.metadata_snapshot != metadata_snapshot:
            try:
                source_version = runtime_version or command_for(snapshot.reference.source_id)[1]
            except (ValueError, RuntimeError):
                source_version = "configured"
            session.add(SourceSnapshot(item_id=item.id, source_id=snapshot.reference.source_id,
                connection_id=connection_id, runtime_version=source_version,
                metadata_snapshot=metadata_snapshot))
        if snapshot.kind == "collection":
            for entry in snapshot.entries:
                child = _upsert(session, entry.reference, entry.kind, entry.title,
                                connection_id=connection_id,
                                published_at=entry.published_at if "published_at" in entry.model_fields_set else _MISSING,
                                capabilities=entry.capabilities if "capabilities" in entry.model_fields_set else _MISSING,
                                is_live=entry.is_live if "is_live" in entry.model_fields_set else _MISSING)
                session.flush()
                if child.id == item.id:
                    continue
                identity = (CollectionEntry.occurrence_key == entry.occurrence_id
                            if entry.occurrence_id else
                            (CollectionEntry.item_id == child.id) & CollectionEntry.occurrence_key.is_(None))
                membership = session.scalar(select(CollectionEntry).where(
                    CollectionEntry.collection_id == item.id, identity))
                if membership:
                    membership.item_id = child.id
                    membership.position = entry.position
                    membership.group = entry.group
                    membership.episode_number = entry.episode_number
                else:
                    session.add(CollectionEntry(collection_id=item.id, item_id=child.id,
                        position=entry.position, group=entry.group,
                        episode_number=entry.episode_number,
                        occurrence_key=entry.occurrence_id))
            # An incomplete scan must never infer removal. This prototype leaves
            # old members in place even after a complete scan until policy exists.
            session.add(CollectionScan(collection_id=item.id, source_id=snapshot.reference.source_id,
                complete=snapshot.enumeration_complete, entry_count=len(snapshot.entries),
                connection_id=connection_id, next_cursor=next_cursor,
                runtime_version=runtime_version, error=scan_error))
        if snapshot.kind == "movie":
            for extra in snapshot.extras:
                child = _upsert(session, extra.reference, "movie_extra", extra.title,
                                connection_id=connection_id,
                                capabilities=extra.capabilities if "capabilities" in extra.model_fields_set else _MISSING)
                child.parent_id = child.parent_id or item.id
                child.extra_type = extra.extra_type or "other"
                session.flush()
                membership = session.scalar(select(MovieExtraParent).where(
                    MovieExtraParent.movie_id == item.id, MovieExtraParent.extra_id == child.id))
                if not membership:
                    session.add(MovieExtraParent(movie_id=item.id, extra_id=child.id,
                        extra_type=child.extra_type))
        result = _serialize(session, item)
        imported_item_id = item.id
        session.commit()
    if snapshot.kind == "collection":
        from backend.api.endpoints.vodloft.feeds import reconcile_live_admissions
        reconcile_live_admissions(imported_item_id)
    return result


@router.post("/library/{collection_id}/refresh")
def refresh_collection(collection_id: int, reference_id: int | None = None,
                       expand_depth: int = 0, max_nested: int = 20):
    if not 0 <= expand_depth <= 3 or not 1 <= max_nested <= 25:
        raise HTTPException(422, "Choose up to three nested levels and 25 nested Collections")
    result = _refresh_collection_one(collection_id, reference_id)
    if not expand_depth:
        return result

    visited = {collection_id}
    refreshed: list[int] = []
    skipped: list[dict] = []

    def expand(parent_id: int, parent_reference_id: int | None, depth: int) -> None:
        if depth >= expand_depth:
            return
        with get_session() as session:
            parent = _reference_for(session, parent_id, reference_id=parent_reference_id)
            children = []
            for entry in session.scalars(select(CollectionEntry).where(
                CollectionEntry.collection_id == parent_id).order_by(CollectionEntry.position)).all():
                child = session.get(MediaItem, entry.item_id)
                if not child or child.kind != "collection":
                    continue
                references = session.scalars(select(SourceReference).where(
                    SourceReference.item_id == child.id,
                    SourceReference.source_id == parent.source_id,
                    SourceReference.connection_id == parent.connection_id)).all()
                children.append((child.id, references[0].id if len(references) == 1 else None))
        for child_id, child_reference_id in children:
            if child_id in visited:
                skipped.append({"item_id": child_id, "reason": "Collection cycle or repeated reference"})
                continue
            visited.add(child_id)
            if len(refreshed) >= max_nested:
                skipped.append({"item_id": child_id, "reason": "Nested Collection limit reached"})
                continue
            if child_reference_id is None:
                skipped.append({"item_id": child_id, "reason": "No unambiguous Source reference in this account"})
                continue
            try:
                _refresh_collection_one(child_id, child_reference_id)
            except HTTPException as exc:
                skipped.append({"item_id": child_id, "reason": f"Nested Source could not refresh ({exc.status_code})"})
                continue
            refreshed.append(child_id)
            expand(child_id, child_reference_id, depth + 1)

    expand(collection_id, reference_id, 0)
    return result | {"nested_expansion": {"refreshed_ids": refreshed, "skipped": skipped}}


def _refresh_collection_one(collection_id: int, reference_id: int | None = None):
    with get_session() as session:
        collection = session.get(MediaItem, collection_id)
        if not collection or collection.kind != "collection":
            raise HTTPException(404, "Collection not found")
        reference = _reference_for(session, collection_id, reference_id=reference_id)
        if not reference:
            raise HTTPException(409, "Select an available Source reference for this Collection")
        source_id, url = reference.source_id, reference.url
        connection_id = reference.connection_id
        options = source_options(session, source_id, connection_id)
    try:
        gateway = SourceGateway()
        snapshot = gateway.resolve(source_id, url, **options)
    except Exception as exc:
        raise _source_problem(exc, "Collection Source is unavailable") from exc
    if snapshot.kind != "collection":
        raise HTTPException(409, "Source no longer identifies this URL as a collection")
    runtime_version = None
    try:
        runtime_version = command_for(source_id)[1]
    except (ValueError, RuntimeError):
        runtime_version = "configured"
    entries, cursor = [], None
    with get_session() as session:
        previous = session.scalar(select(CollectionScan).where(
            CollectionScan.collection_id == collection_id,
            CollectionScan.source_id == source_id,
            CollectionScan.connection_id == connection_id,
        ).order_by(CollectionScan.id.desc()))
        if (previous and not previous.complete and previous.next_cursor and
            previous.runtime_version == runtime_version):
            cursor = previous.next_cursor
    resumed = cursor is not None
    try:
        paged = next((m for m in gateway.manifests() if m.source_id == source_id), None)
        if paged and "enumerate_pages" in paged.capabilities:
            complete = False
            seen_cursors = set()
            # Nested Collections are traversed only by explicit bounded expansion.
            for _ in range(100):
                page = gateway.entries(source_id, url, cursor=cursor, limit=50, **options)
                entries.extend(page.entries)
                if page.complete:
                    complete = True
                    cursor = None
                    break
                if not page.next_cursor or page.next_cursor in seen_cursors:
                    break
                cursor = page.next_cursor
                seen_cursors.add(cursor)
            snapshot = snapshot.model_copy(update={"entries": entries,
                "enumeration_complete": complete})
            return _import_snapshot(snapshot, connection_id, next_cursor=cursor,
                runtime_version=runtime_version)
    except Exception:
        logger.exception("Collection %s enumeration stopped before completion", collection_id)
        snapshot = snapshot.model_copy(update={"entries": entries or snapshot.entries,
            "enumeration_complete": False})
        return _import_snapshot(snapshot, connection_id,
            scan_error="Collection enumeration stopped before completion",
            next_cursor=cursor if entries or not resumed else None,
            runtime_version=runtime_version)
    return _import_snapshot(snapshot, connection_id, runtime_version=runtime_version)


@router.post("/library/{item_id}/refresh-details")
def refresh_details(item_id: int, reference_id: int | None = None):
    """Hydrate one playable item after lightweight Collection enumeration."""
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        if not item or item.kind == "collection":
            raise HTTPException(404, "Playable media item not found")
        reference = _reference_for(session, item_id, reference_id=reference_id)
        if not reference:
            raise HTTPException(409, "Select an available Source reference for this item")
        source_id, url = reference.source_id, reference.url
        connection_id = reference.connection_id
        options = source_options(session, source_id, connection_id)
    try:
        snapshot = SourceGateway().resolve(source_id, url, **options)
    except Exception as exc:
        raise _source_problem(exc, "Source could not refresh this item") from exc
    if snapshot.kind == "collection" or snapshot.reference.source_id != source_id:
        raise HTTPException(409, "Source no longer identifies this URL as the same playable item")
    with get_session() as session:
        old = session.get(SourceReference, reference.id)
        domain = session.get(Domain, old.domain_id)
        if (snapshot.reference.domain != domain.hostname or
            snapshot.reference.namespace != old.namespace or
            snapshot.reference.upstream_id != old.upstream_id):
            raise HTTPException(409, "Source changed the item identity; add the URL as new media")
    return _import_snapshot(snapshot, connection_id)


@router.get("/library")
def library():
    with get_session() as session:
        items = session.scalars(select(MediaItem).order_by(MediaItem.created_at.desc())).all()
        members = set(session.scalars(select(CollectionEntry.item_id)).all())
        return [_serialize(session, item) for item in items if item.id not in members and
                (item.kind != "movie_extra" or item.parent_id is None)]


@router.get("/home")
def home(request: Request):
    with get_session() as session:
        progress = session.scalars(select(PlaybackProgress).where(
            PlaybackProgress.user_key == principal(request).key, PlaybackProgress.completed.is_(False))
            .order_by(PlaybackProgress.updated_at.desc()).limit(12)).all()
        recent = session.scalars(select(MediaItem).where(MediaItem.kind != "collection")
            .order_by(MediaItem.created_at.desc()).limit(12)).all()
        active = session.scalars(select(AcquisitionJob).where(AcquisitionJob.state.in_([
            "queued", "resolving", "downloading", "processing", "verifying", "finalizing"]))
            .order_by(AcquisitionJob.created_at.desc()).limit(12)).all()
        failures = session.scalars(select(AcquisitionJob).where(AcquisitionJob.state == "failed")
            .order_by(AcquisitionJob.updated_at.desc()).limit(10)).all()
        exports = session.scalars(select(MediaServerExport).where(MediaServerExport.state == "failed")
            .order_by(MediaServerExport.updated_at.desc()).limit(10)).all()
        return {"continue": [{**_serialize(session, session.get(MediaItem, p.item_id)),
            "seconds": p.seconds} for p in progress if session.get(MediaItem, p.item_id)],
            "recent": [_serialize(session, item) for item in recent],
            "activity": [{"id": job.id, "item_id": job.item_id, "state": job.state} for job in active],
            "issues": [{"kind": "acquisition", "id": job.id, "item_id": job.item_id}
                       for job in failures] +
                      [{"kind": "delivery", "id": export.id} for export in exports]}


@router.get("/library/{item_id}/progress")
def playback_progress(item_id: int, request: Request):
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        if not item or item.kind == "collection":
            raise HTTPException(404, "Playable media item not found")
        progress = session.scalar(select(PlaybackProgress).where(
            PlaybackProgress.user_key == principal(request).key, PlaybackProgress.item_id == item_id))
        return {"seconds": progress.seconds if progress else 0,
                "completed": progress.completed if progress else False}


@router.put("/library/{item_id}/progress")
def save_playback_progress(item_id: int, data: PlaybackInput, request: Request):
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        if not item or item.kind == "collection":
            raise HTTPException(404, "Playable media item not found")
        progress = session.scalar(select(PlaybackProgress).where(
            PlaybackProgress.user_key == principal(request).key, PlaybackProgress.item_id == item_id))
        if not progress:
            progress = PlaybackProgress(user_key=principal(request).key, item_id=item_id)
            session.add(progress)
        progress.seconds, progress.completed = data.seconds, data.completed
        session.commit()
        return {"seconds": progress.seconds, "completed": progress.completed}


@router.get("/library/{item_id}")
def library_item(item_id: int, request: Request):
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        if not item:
            raise HTTPException(404, "Media item not found")
        result = _serialize(session, item)
        result["references"] = [{"id": reference.id, "source_id": reference.source_id,
            "connection_id": reference.connection_id, "namespace": reference.namespace,
            "upstream_id": reference.upstream_id} for reference in session.scalars(
                select(SourceReference).where(SourceReference.item_id == item_id)).all()
                if principal(request).can_use_connection(reference.connection_id)]
        if item.kind == "collection":
            entries = session.scalars(select(CollectionEntry).where(
                CollectionEntry.collection_id == item_id).order_by(CollectionEntry.position)).all()
            result["entries"] = [_serialize(session, session.get(MediaItem, e.item_id)) for e in entries]
        if item.kind == "movie":
            extras = session.scalars(select(MovieExtraParent).where(MovieExtraParent.movie_id == item_id)).all()
            result["extras"] = [_serialize(session, session.get(MediaItem, e.extra_id)) for e in extras]
        return result


@router.get("/library/{item_id}/source-history")
def source_history(item_id: int):
    with get_session() as session:
        if not session.get(MediaItem, item_id):
            raise HTTPException(404, "Media item not found")
        snapshots = session.scalars(select(SourceSnapshot).where(
            SourceSnapshot.item_id == item_id).order_by(SourceSnapshot.id.desc()).limit(50)).all()
        return [{"id": snapshot.id, "source_id": snapshot.source_id,
                 "connection_id": snapshot.connection_id,
                 "runtime_version": snapshot.runtime_version,
                 "created_at": snapshot.created_at,
                 "metadata": snapshot.metadata_snapshot} for snapshot in snapshots]


@router.post("/library/{item_id}/source-history/{snapshot_id}/restore")
def restore_source_metadata(item_id: int, snapshot_id: int):
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        snapshot = session.get(SourceSnapshot, snapshot_id)
        if not item or not snapshot or snapshot.item_id != item_id:
            raise HTTPException(404, "Source snapshot not found")
        values = snapshot.metadata_snapshot
        for field in ("title", "description", "duration", "artwork_url", "capabilities"):
            if field in values:
                setattr(item, field, values[field])
        if "published_at" in values:
            item.published_at = datetime.fromisoformat(values["published_at"]) if values["published_at"] else None
        item.normalized_metadata = {**(item.normalized_metadata or {}), **{key: values[key]
            for key in ("artwork", "chapters", "tracks", "author", "movie_year") if key in values}}
        session.commit()
        return _serialize(session, item)


@router.delete("/library/{item_id}", status_code=204)
def delete_collection(item_id: int):
    """Remove Collection demand without deleting media shared with other views."""
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        if not item or item.kind != "collection":
            raise HTTPException(404, "Collection not found")
        if session.scalar(select(Artifact.id).where(Artifact.item_id == item_id)):
            raise HTTPException(409, "This Collection has a local artifact; remove its placement first")
        subscriptions = session.scalars(select(FeedSubscription).where(
            FeedSubscription.collection_id == item_id)).all()
        subscription_ids = [subscription.id for subscription in subscriptions]
        for subscription_id in subscription_ids:
            session.execute(delete(PublishedEntry).where(PublishedEntry.subscription_id == subscription_id))
        session.execute(delete(FeedSubscription).where(FeedSubscription.collection_id == item_id))
        session.execute(delete(LiveAdmission).where(LiveAdmission.stream_profile_id.in_(
            select(CollectionStreamProfile.id).where(CollectionStreamProfile.collection_id == item_id))))
        session.execute(delete(CollectionStreamProfile).where(CollectionStreamProfile.collection_id == item_id))
        session.execute(delete(MediaDemand).where(MediaDemand.owner_kind == "policy",
            MediaDemand.owner_id.in_(select(CollectionDownloadProfile.id).where(
                CollectionDownloadProfile.collection_id == item_id))))
        session.execute(delete(CollectionDownloadProfile).where(CollectionDownloadProfile.collection_id == item_id))
        session.execute(delete(CollectionScan).where(CollectionScan.collection_id == item_id))
        session.execute(delete(CollectionEntry).where(or_(
            CollectionEntry.collection_id == item_id, CollectionEntry.item_id == item_id)))
        session.execute(delete(SourceReference).where(SourceReference.item_id == item_id))
        session.execute(delete(SourceSnapshot).where(SourceSnapshot.item_id == item_id))
        session.execute(delete(LegacyMediaLink).where(LegacyMediaLink.item_id == item_id))
        session.delete(item)
        session.commit()
    root = Path(get_settings().download_settings.download_root).resolve() / "vodloft-feeds"
    for subscription_id in subscription_ids:
        shutil.rmtree(root / str(subscription_id), ignore_errors=True)


@router.put("/library/{item_id}/metadata")
def edit_metadata(item_id: int, data: UserMetadataInput):
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        if not item:
            raise HTTPException(404, "Media item not found")
        if "title" in data.model_fields_set:
            item.user_title = data.title.strip() if data.title and data.title.strip() else None
        if "description" in data.model_fields_set:
            item.user_description = data.description.strip() if data.description and data.description.strip() else None
        if data.kind:
            if item.kind == "collection":
                raise HTTPException(422, "A Collection cannot be reclassified as playable media")
            item.kind, item.user_kind = data.kind, data.kind
        if "parent_id" in data.model_fields_set:
            parent = session.get(MediaItem, data.parent_id) if data.parent_id else None
            if data.parent_id and (not parent or parent.kind != "movie" or parent.id == item.id):
                raise HTTPException(422, "Choose a different Movie as this extra's parent")
            if parent and item.kind != "movie_extra":
                raise HTTPException(422, "Only Movie Extras can have a parent Movie")
            session.execute(delete(MovieExtraParent).where(MovieExtraParent.extra_id == item.id))
            item.parent_id = data.parent_id
            if parent:
                session.add(MovieExtraParent(movie_id=parent.id, extra_id=item.id,
                    extra_type=data.extra_type or item.extra_type or "other"))
        if "extra_type" in data.model_fields_set:
            item.extra_type = data.extra_type
        if item.kind != "movie_extra":
            item.parent_id, item.extra_type = None, None
            session.execute(delete(MovieExtraParent).where(MovieExtraParent.extra_id == item.id))
        session.commit()
        return _serialize(session, item)


def _run_download(job_id: int) -> None:
    owner = _claim_job(job_id)
    if not owner:
        return
    stop = threading.Event()
    heartbeat = threading.Thread(target=_heartbeat_job, args=(job_id, owner, stop),
                                 daemon=True, name=f"vodloft-lease-{job_id}")
    heartbeat.start()
    try:
        with _download_slots:
            with get_session() as session:
                job = session.get(AcquisitionJob, job_id)
                if not job:
                    return
                reference = session.get(SourceReference, job.reference_id)
                source_id, domain_id, connection_id = (
                    reference.source_id, reference.domain_id, reference.connection_id)
            with _source_slots_lock:
                source_slot = _source_slots.setdefault(source_id, threading.BoundedSemaphore(3))
                domain_slot = _domain_slots.setdefault(domain_id, threading.BoundedSemaphore(2))
                connection_slot = (_connection_slots.setdefault(connection_id, threading.BoundedSemaphore(1))
                                   if connection_id else nullcontext())
            with source_slot, domain_slot, connection_slot:
                _execute_leased_download(job_id)
    finally:
        stop.set()
        heartbeat.join(timeout=1)
        with get_session() as session:
            session.execute(update(AcquisitionJob).where(
                AcquisitionJob.id == job_id, AcquisitionJob.lease_owner == owner).values(
                    lease_owner=None, lease_until=None))
            session.commit()


def _claim_job(job_id: int) -> str | None:
    owner = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    with get_session() as session:
        claimed = session.execute(update(AcquisitionJob).where(
            AcquisitionJob.id == job_id,
            AcquisitionJob.state.in_(["queued", "resolving", "downloading", "processing", "verifying", "finalizing"]),
            or_(AcquisitionJob.lease_until.is_(None), AcquisitionJob.lease_until < now)).values(
                lease_owner=owner, lease_until=now + timedelta(seconds=45)))
        session.commit()
        return owner if claimed.rowcount == 1 else None


def _heartbeat_job(job_id: int, owner: str, stop: threading.Event) -> None:
    while not stop.wait(10):
        try:
            with get_session() as session:
                result = session.execute(update(AcquisitionJob).where(
                    AcquisitionJob.id == job_id, AcquisitionJob.lease_owner == owner).values(
                    lease_until=datetime.now(timezone.utc) + timedelta(seconds=45)))
                session.commit()
                if not result.rowcount:
                    return
        except Exception:
            logger.exception("Acquisition job %s lease heartbeat failed", job_id)


def _execute_leased_download(job_id: int) -> None:
    with get_session() as session:
        job = session.get(AcquisitionJob, job_id)
        if not job or job.state not in ("queued", "resolving", "downloading", "processing", "verifying", "finalizing"):
            return
        if job.cancel_requested:
            job.state, job.active_key = "canceled", None
            _sync_operation(session, job)
            session.commit()
            clear_canceled_job(job_id)
            return
        reference = session.get(SourceReference, job.reference_id)
        item_id, source_id, url, reference_id = (
            job.item_id, reference.source_id, reference.url, reference.id)
        connection_id = reference.connection_id
        profile_id = job.profile_id
        spec = dict(job.execution_spec or {})
        job.state = "resolving"
        job.attempts += 1
        _sync_operation(session, job)
        session.commit()
    root = Path(get_settings().download_settings.download_root).resolve() / "vodloft"
    try:
        with get_session() as session:
            options = source_options(session, source_id, connection_id)
        if not root.parent.is_dir():
            raise OSError("Download storage is unavailable")
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"job-{job_id}-", dir=root) as staging:
            _job_stage(job_id, "downloading")
            command = spec.get("source_command")
            gateway = SourceGateway({source_id: command}) if command else SourceGateway()
            result = gateway.download(source_id, url, staging,
                preferred_format=spec.get("preferred_format", "format_1080p"), job_id=job_id,
                representation=spec.get("representation", {}), metadata=spec.get("metadata", {}),
                on_progress=lambda percent: _download_progress(job_id, percent), **options)
            _job_stage(job_id, "verifying")
            source_file = Path(staging, result.filename).resolve()
            if source_file.parent != Path(staging).resolve() or not source_file.is_file() or source_file.stat().st_size != result.size:
                raise RuntimeError("Source returned an invalid artifact manifest")
            suffix = source_file.suffix.lower()
            if suffix not in {".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".ogg", ".wav", ".mov"}:
                raise RuntimeError("Unsupported media output format")
            destination = root / f"{item_id}-{job_id}{suffix}"
            output = (output_path_from_spec(spec["output_template"], spec["values"], suffix.lstrip("."))
                      if profile_id else None)
            vodloft_finalization.prepare(job_id, destination, output)
            _job_stage(job_id, "finalizing")
            os.replace(source_file, destination)
            vodloft_finalization.advance(job_id, "content")
            with get_session() as session:
                placement_id = None
                artifact = Artifact(item_id=item_id, profile_id=profile_id,
                                    source_reference_id=reference_id,
                                    representation_key=spec.get("representation_key"),
                                    path=str(destination), size=result.size)
                session.add(artifact)
                session.flush()
                if profile_id:
                    occupied = session.scalar(select(ArtifactPlacement).where(ArtifactPlacement.path == str(output)))
                    if occupied and (occupied.profile_id != profile_id or
                                     session.get(Artifact, occupied.artifact_id).item_id != item_id):
                        raise ValueError("Output path belongs to a different Local Media Profile")
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".vodloft-", delete=False) as tmp:
                        with destination.open("rb") as input_file:
                            shutil.copyfileobj(input_file, tmp)
                        temporary_path = Path(tmp.name)
                    if occupied:
                        os.replace(temporary_path, output)
                        occupied.artifact_id = artifact.id
                        placement_id = occupied.id
                    else:
                        try:
                            os.link(temporary_path, output)
                        finally:
                            temporary_path.unlink(missing_ok=True)
                        placement = ArtifactPlacement(artifact_id=artifact.id,
                            profile_id=profile_id, path=str(output))
                        session.add(placement)
                        session.flush()
                        placement_id = placement.id
                completed = session.get(AcquisitionJob, job_id)
                completed.state, completed.active_key = "available", None
                _sync_operation(session, completed)
                session.delete(session.scalar(select(FileFinalization).where(FileFinalization.job_id == job_id)))
                session.commit()
            if profile_id and placement_id:
                try:
                    from backend.api.endpoints.vodloft.integrations import dispatch_exports
                    dispatch_exports(profile_id, placement_id)
                except Exception:
                    logger.exception("Download %s is available, but media-server delivery could not be queued", job_id)
    except Exception as exc:
        with get_session() as session:
            job = session.get(AcquisitionJob, job_id)
            canceled = job.cancel_requested or isinstance(exc, JobCancelled)
            if not canceled:
                logger.exception("Acquisition job %s failed", job_id)
            stage = job.state
            code = (exc.code if isinstance(exc, SourceInvocationError) else
                    "insufficient_disk" if isinstance(exc, OSError) and exc.errno == errno.ENOSPC else
                    "unavailable" if isinstance(exc, (OSError, TimeoutError)) else "runtime_error")
            job.state, job.active_key, job.error = (
                "canceled" if canceled else "failed", None,
                None if canceled else str(exc) if isinstance(exc, SourceInvocationError) else
                "Insufficient disk space" if code == "insufficient_disk" else
                f"Acquisition failed during {stage}")
            job.error_code = None if canceled else code
            job.failed_stage = None if canceled else stage
            _sync_operation(session, job)
            session.commit()
        try:
            vodloft_finalization.reconcile(job_id)
        except Exception:
            logger.exception("Finalization journal %s still needs reconciliation", job_id)
        clear_canceled_job(job_id)


def _job_stage(job_id: int, stage: str) -> None:
    with get_session() as session:
        job = session.get(AcquisitionJob, job_id)
        if job.cancel_requested:
            raise JobCancelled()
        job.state = stage
        _sync_operation(session, job)
        session.commit()


def recover_acquisition_jobs() -> None:
    """Resume jobs whose HTTP background task was interrupted by a restart."""
    with get_session() as session:
        jobs = session.scalars(select(AcquisitionJob).where(
            AcquisitionJob.state.in_(["queued", "resolving", "downloading", "processing", "verifying", "finalizing"]))).all()
        now = datetime.now(timezone.utc)
        eligible = [job for job in jobs if not job.lease_until or
                    job.lease_until.replace(tzinfo=job.lease_until.tzinfo or timezone.utc) < now]
        ids = [job.id for job in eligible]
        for job in eligible:
            if job.cancel_requested:
                job.state, job.active_key = "canceled", None
            else:
                job.state = "queued"
            job.lease_owner, job.lease_until = None, None
            _sync_operation(session, job)
        session.commit()
    for job_id in ids:
        with get_session() as session:
            if session.get(AcquisitionJob, job_id).state != "queued":
                continue
        threading.Thread(target=_run_download, args=(job_id,),
                         name=f"vodloft-recover-{job_id}", daemon=True).start()


def retry_due_acquisition_jobs() -> None:
    """Bounded exponential retry; the original frozen execution spec is retained."""
    now = datetime.now(timezone.utc)
    with get_session() as session:
        jobs = session.scalars(select(AcquisitionJob).where(
            AcquisitionJob.state == "failed", AcquisitionJob.attempts < 3,
            AcquisitionJob.cancel_requested.is_(False))).all()
        ready = []
        for job in jobs:
            profile = session.get(DomainLocalMediaProfile, job.profile_id)
            if profile and (profile.deleted or not profile.enabled or profile.impairment):
                continue
            age = now - job.updated_at.replace(tzinfo=job.updated_at.tzinfo or timezone.utc)
            delay = max(300 if job.error_code == "rate_limited" else 0,
                        30 * (2 ** max(job.attempts - 1, 0)))
            if age < timedelta(seconds=delay):
                continue
            key = f"{job.item_id}:{job.profile_id}"
            if session.scalar(select(AcquisitionJob.id).where(AcquisitionJob.active_key == key)):
                continue
            job.state, job.error, job.error_code, job.failed_stage = "queued", None, None, None
            job.active_key = key
            _sync_operation(session, job)
            ready.append(job.id)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return
    for job_id in ready:
        threading.Thread(target=_run_download, args=(job_id,), daemon=True,
                         name=f"vodloft-retry-{job_id}").start()


def queue_download(item_id: int, profile_id: int | None, *, collection_id: int | None = None,
                   reference_id: int | None = None, collection_reference_id: int | None = None,
                   policy_id: int | None = None, request_id: int | None = None,
                   force: bool = False) -> tuple[int | None, str, bool]:
    """Freeze a Domain profile for one playable item; null means already satisfied."""
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        if not item or item.kind == "collection":
            raise HTTPException(404, "Playable media item not found")
        if not Path(get_settings().download_settings.download_root).resolve().is_dir():
            raise HTTPException(503, "Download storage is unavailable")
        if item.capabilities is not None and "download" not in item.capabilities:
            raise HTTPException(409, "The Source does not advertise download for this media item")
        if profile_id is not None:
            suppressed = session.scalar(select(MediaSuppression).where(
                MediaSuppression.item_id == item_id, MediaSuppression.profile_id == profile_id))
            if suppressed and not force:
                return None, "suppressed", False
            if suppressed:
                session.delete(suppressed)
                session.flush()
            owner_kind, owner_id = (("request", request_id) if request_id else
                ("policy", policy_id) if policy_id else ("direct", item_id))
            if not session.scalar(select(MediaDemand.id).where(MediaDemand.item_id == item_id,
                MediaDemand.profile_id == profile_id, MediaDemand.owner_kind == owner_kind,
                MediaDemand.owner_id == owner_id)):
                session.add(MediaDemand(item_id=item_id, profile_id=profile_id,
                    owner_kind=owner_kind, owner_id=owner_id))
                session.flush()
        existing = session.scalar(select(AcquisitionJob).where(
            AcquisitionJob.active_key == f"{item_id}:{profile_id}"))
        if existing:
            if reference_id is not None and existing.reference_id != reference_id:
                raise HTTPException(409, "This profile has an active download through another Source reference")
            if collection_id is not None:
                selected = _reference_for(session, item_id, collection_id=collection_id,
                    collection_reference_id=collection_reference_id)
                if not selected or existing.reference_id != selected.id:
                    raise HTTPException(409, "This profile has an active download through another Source account")
            session.commit()
            return existing.id, existing.state, False
        reference = _reference_for(session, item_id, reference_id=reference_id,
                                   collection_id=collection_id,
                                   collection_reference_id=collection_reference_id)
        if not reference:
            raise HTTPException(409, "Select an available Source and account reference for this item")
        query = select(DomainLocalMediaProfile).where(
            DomainLocalMediaProfile.domain_id == item.domain_id,
            DomainLocalMediaProfile.enabled.is_(True),
            DomainLocalMediaProfile.deleted.is_(False), DomainLocalMediaProfile.impairment.is_(None))
        if profile_id is not None:
            query = query.where(DomainLocalMediaProfile.id == profile_id)
        profile = next((p for p in session.scalars(query).all() if item.kind in p.applicable_kinds), None)
        if not profile:
            raise HTTPException(409, "Create and select a Local Media Profile for this Domain and media type")
        if item.formats and profile.preferred_format not in {fmt.get("code") for fmt in item.formats}:
            raise HTTPException(409, "The Source does not offer this item's requested format")
        representation_key = hashlib.sha256(json.dumps({
            "source_id": reference.source_id, "namespace": reference.namespace,
            "upstream_id": reference.upstream_id, "connection_key": reference.connection_key,
            "format": profile.preferred_format, "media_type": item.kind,
            "representation": RepresentationPolicy.model_validate(profile.representation or {}).model_dump(),
            "metadata": {"title": item.user_title or item.title,
                         "description": item.user_description or item.description or ""}
                         if (profile.representation or {}).get("embed_metadata", True) else {},
        }, sort_keys=True).encode()).hexdigest()
        domain = session.get(Domain, item.domain_id)
        membership = session.scalar(select(CollectionEntry).where(CollectionEntry.collection_id == collection_id,
            CollectionEntry.item_id == item_id)) if collection_id else None
        values = template_values(item, domain, reference, membership=membership,
            collection=(session.get(MediaItem, collection_id).user_title or
                        session.get(MediaItem, collection_id).title) if collection_id else "")
        if not force:
            compatible = next((artifact for artifact in session.scalars(select(Artifact).where(
                Artifact.item_id == item_id, Artifact.representation_key == representation_key)
                .order_by(Artifact.id.desc())).all() if Path(artifact.path).is_file()), None)
            if compatible:
                placement = session.scalar(select(ArtifactPlacement).where(
                    ArtifactPlacement.artifact_id == compatible.id,
                    ArtifactPlacement.profile_id == profile.id))
                if placement and Path(placement.path).is_file():
                    session.commit()
                    return None, "available", False
                output = output_path_from_spec(profile.output_template, values,
                    Path(compatible.path).suffix.lstrip("."))
                occupied = session.scalar(select(ArtifactPlacement).where(
                    ArtifactPlacement.path == str(output)))
                if occupied:
                    raise HTTPException(409, "The output path belongs to another representation")
                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists():
                    if not output.is_file() or not filecmp.cmp(compatible.path, output, shallow=False):
                        raise HTTPException(409, "The output path contains an unmanaged file")
                else:
                    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".vodloft-",
                                                     delete=False) as temporary:
                        with Path(compatible.path).open("rb") as input_file:
                            shutil.copyfileobj(input_file, temporary)
                        temporary_path = Path(temporary.name)
                    try:
                        os.link(temporary_path, output)
                    finally:
                        temporary_path.unlink(missing_ok=True)
                placement = ArtifactPlacement(artifact_id=compatible.id,
                    profile_id=profile.id, path=str(output))
                session.add(placement)
                session.commit()
                try:
                    from backend.api.endpoints.vodloft.integrations import dispatch_exports
                    dispatch_exports(profile.id, placement.id)
                except Exception:
                    logger.exception("Media-server delivery for reused artifact %s failed", compatible.id)
                return None, "available", False
        gateway = SourceGateway()
        selected_command = gateway.commands.get(reference.source_id)
        try:
            runtime_version = command_for(reference.source_id)[1]
        except ValueError:
            runtime_version = "configured"
        spec = {"preferred_format": profile.preferred_format,
                "representation": RepresentationPolicy.model_validate(profile.representation or {}).model_dump(),
                "metadata": {"title": item.user_title or item.title,
                             "description": item.user_description or item.description or ""},
                "representation_key": representation_key,
                "output_template": profile.output_template, "profile_id": profile.id,
                "profile_revision": profile.updated_at.isoformat() if profile.updated_at else None,
                "source_id": reference.source_id, "reference_id": reference.id,
                "source_command": selected_command, "runtime_version": runtime_version,
                "connection_id": reference.connection_id, "queued_at": datetime.now(timezone.utc).isoformat(),
                "values": values}
        job = AcquisitionJob(item_id=item_id, reference_id=reference.id,
            profile_id=profile.id, execution_spec=spec, state="queued",
            active_key=f"{item_id}:{profile.id}")
        session.add(job)
        try:
            session.flush()
            operation = TaskOperation(id=str(uuid.uuid4()), kind="vodloft_acquisition",
                source="UI" if collection_id is None else "SYSTEM",
                resource_type="vodloft_media", resource_id=item_id,
                title=f"Download {item.user_title or item.title}"[:255],
                status="QUEUED", progress=0, message="Queued",
                context={"job_id": job.id, "profile_id": profile.id})
            session.add(operation)
            job.operation_id = operation.id
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.scalar(select(AcquisitionJob).where(AcquisitionJob.active_key == f"{item_id}:{profile.id}"))
            if existing:
                if existing.reference_id != reference.id:
                    raise HTTPException(409, "This profile has an active download through another Source account")
                return existing.id, existing.state, False
            raise
        return job.id, job.state, True


@router.post("/library/{item_id}/download")
def download_item(item_id: int, background: BackgroundTasks, request: DownloadRequest | None = None):
    job_id, state, created = queue_download(item_id, request.profile_id if request else None,
        reference_id=request.reference_id if request else None, force=True)
    if not created:
        return {"id": job_id, "state": state}
    background.add_task(_run_download, job_id)
    return {"id": job_id, "state": state}


@router.delete("/library/{item_id}/local/{profile_id}")
def remove_local_representation(item_id: int, profile_id: int):
    """Intentional removal suppresses every policy until the user resumes it."""
    with get_session() as session:
        if not session.get(MediaItem, item_id):
            raise HTTPException(404, "Media item not found")
        suppression = session.scalar(select(MediaSuppression).where(
            MediaSuppression.item_id == item_id, MediaSuppression.profile_id == profile_id))
        if not suppression:
            session.add(MediaSuppression(item_id=item_id, profile_id=profile_id))
        session.execute(delete(MediaDemand).where(MediaDemand.item_id == item_id,
            MediaDemand.profile_id == profile_id))
        active = session.scalars(select(AcquisitionJob).where(
            AcquisitionJob.item_id == item_id, AcquisitionJob.profile_id == profile_id,
            AcquisitionJob.active_key.is_not(None))).all()
        for job in active:
            job.cancel_requested = True
            if job.state == "queued":
                job.state, job.active_key = "canceled", None
                _sync_operation(session, job)
        session.commit()
        ids = [job.id for job in active]
    for job_id in ids:
        cancel_running_job(job_id)
    from backend.services.vodloft_retention import reconcile
    return {"suppressed": True, "removed": reconcile(grace_hours=0)}


@router.post("/library/{item_id}/local/{profile_id}/resume")
def resume_local_representation(item_id: int, profile_id: int):
    with get_session() as session:
        suppression = session.scalar(select(MediaSuppression).where(
            MediaSuppression.item_id == item_id, MediaSuppression.profile_id == profile_id))
        if not suppression:
            raise HTTPException(404, "Suppression not found")
        session.delete(suppression)
        session.commit()
    return {"suppressed": False}


@router.get("/jobs")
def jobs(limit: int = 50):
    if not 1 <= limit <= 100:
        raise HTTPException(422, "Choose between 1 and 100 recent jobs")
    with get_session() as session:
        recent = session.scalars(select(AcquisitionJob).order_by(
            AcquisitionJob.created_at.desc(), AcquisitionJob.id.desc()).limit(limit)).all()
        return [{"id": job.id, "item_id": job.item_id,
                 "title": (item.user_title or item.title) if (item := session.get(MediaItem, job.item_id)) else "Removed item",
                 "state": job.state, "attempts": job.attempts,
                 "error_code": job.error_code, "failed_stage": job.failed_stage,
                 "progress": _progress_for(session, job),
                 "created_at": job.created_at} for job in recent]


@router.get("/jobs/{job_id}")
def job_status(job_id: int, request: Request):
    with get_session() as session:
        job = session.get(AcquisitionJob, job_id)
        if not job:
            raise HTTPException(404, "Acquisition job not found")
        actor = principal(request)
        if not actor.manages_library and not session.scalar(select(LibraryRequest.id).where(
                LibraryRequest.job_id == job_id, LibraryRequest.user_key == actor.key)):
            raise HTTPException(404, "Acquisition job not found")
        return {"id": job.id, "item_id": job.item_id, "state": job.state,
                "error": job.error, "error_code": job.error_code,
                "failed_stage": job.failed_stage, "attempts": job.attempts,
                "cancel_requested": job.cancel_requested, "profile_id": job.profile_id,
                "operation_id": job.operation_id, "progress": _progress_for(session, job)}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    with get_session() as session:
        job = session.get(AcquisitionJob, job_id)
        if not job:
            raise HTTPException(404, "Acquisition job not found")
        if job.state in ("available", "failed", "canceled", "finalizing"):
            raise HTTPException(409, "This job is no longer cancelable")
        was_queued = job.state == "queued"
        job.cancel_requested = True
        if was_queued:
            job.state, job.active_key = "canceled", None
            _sync_operation(session, job)
        session.commit()
    if not was_queued:
        cancel_running_job(job_id)
    return {"id": job_id, "state": "cancel_requested"}


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int):
    with get_session() as session:
        job = session.get(AcquisitionJob, job_id)
        if not job:
            raise HTTPException(404, "Acquisition job not found")
        if job.state not in {"failed", "canceled"}:
            raise HTTPException(409, "Only failed or canceled jobs can be restarted")
        profile = session.get(DomainLocalMediaProfile, job.profile_id)
        if not profile or profile.deleted or not profile.enabled or profile.impairment:
            raise HTTPException(409, "The Local Media Profile is unavailable; choose an enabled profile")
        key = f"{job.item_id}:{job.profile_id}"
        if session.scalar(select(AcquisitionJob.id).where(AcquisitionJob.active_key == key)):
            raise HTTPException(409, "An acquisition is already active for this representation")
        job.state, job.error, job.error_code, job.failed_stage, job.cancel_requested = (
            "queued", None, None, None, False)
        job.active_key = key
        _sync_operation(session, job)
        try:
            session.commit()
        except IntegrityError as exc:
            raise HTTPException(409, "An acquisition is already active") from exc
    threading.Thread(target=_run_download, args=(job_id,), daemon=True,
                     name=f"vodloft-restart-{job_id}").start()
    return {"id": job_id, "state": "queued"}


@router.get("/library/{item_id}/play")
def play(item_id: int):
    with get_session() as session:
        artifact = session.scalar(select(Artifact).where(Artifact.item_id == item_id).order_by(Artifact.id.desc()))
        if not artifact:
            raise HTTPException(404, "This media item has no local file")
        path = Path(artifact.path).resolve()
        root = (Path(get_settings().download_settings.download_root).resolve() / "vodloft")
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404, "Local file is unavailable")
        return RedirectResponse(url=f"/api/vodloft/library/{item_id}/play/version/{path.name}")


@router.get("/library/{item_id}/play/version/{filename}", name="vodloft_play_version")
def play_version(item_id: int, filename: str):
    # A redirect binds subsequent range requests to the same immutable file,
    # even when a newer download is published for this item.
    if not re.fullmatch(rf"{item_id}-[0-9]+\.(?:mp4|mkv|webm|mp3|m4a|opus|ogg|wav|mov)", filename):
        raise HTTPException(404, "Representation not found")
    path = Path(get_settings().download_settings.download_root).resolve() / "vodloft" / filename
    if not path.is_file():
        raise HTTPException(404, "Representation not found")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
