"""Generic Add URL, library, acquisition and local playback prototype."""

import logging
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from backend.db import get_session
from backend.db.models.vodloft import (
    AcquisitionJob, Artifact, ArtifactPlacement, CollectionDownloadProfile, CollectionEntry, CollectionScan, CollectionStreamProfile, Domain, FeedSubscription, FileFinalization, LegacyMediaLink, MediaItem, MediaServerExport, MovieExtraParent, PlaybackProgress, PublishedEntry, SourceConnection, SourceDomain, SourceReference,
)
from backend.db.models.local_media_profile import DomainLocalMediaProfile
from backend.api.endpoints.vodloft.profiles import output_path_from_spec
from backend.source_manager.gateway import SourceGateway, cancel_running_job, clear_canceled_job, validate_public_url
from backend.source_manager.runtime import command_for
from backend.services import vodloft_finalization
from backend.source_manager import runtime as source_runtime
from backend.api.endpoints.vodloft.connections import access_token as connection_token
from config import get_settings
from source_contracts import MediaSnapshot, SourceMediaReference
from task_manager.scheduler.db import TaskOperation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vodloft", tags=["VodLoft library"])
_download_slots = threading.BoundedSemaphore(2)
_source_slots: dict[str, threading.BoundedSemaphore] = {}
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


class JobCancelled(Exception):
    pass


class ResolveRequest(BaseModel):
    url: str = Field(min_length=8)
    source_id: str | None = None
    connection_id: int | None = None


class ImportRequest(BaseModel):
    snapshot: MediaSnapshot
    connection_id: int | None = None


class DownloadRequest(BaseModel):
    profile_id: int | None = None


class UserMetadataInput(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=10000)


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
            published_at=_MISSING) -> MediaItem:
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
                             published_at=None if published_at is _MISSING else published_at)
            session.add(item)
            session.flush()
        session.add(SourceReference(item_id=item.id, domain_id=domain.id,
            source_id=reference.source_id, namespace=reference.namespace,
            upstream_id=reference.upstream_id, url=reference.url,
            connection_id=connection_id, connection_key=connection_id or 0))
    return item


def _reference_for(session, item_id: int) -> SourceReference | None:
    references = session.scalars(select(SourceReference).where(SourceReference.item_id == item_id)).all()
    for reference in references:
        if reference.connection_id:
            connection = session.get(SourceConnection, reference.connection_id)
            if not connection or not connection.enabled:
                continue
        return reference
    return None


def _serialize(session, item: MediaItem) -> dict:
    domain = session.get(Domain, item.domain_id)
    artifact = session.scalar(select(Artifact).where(Artifact.item_id == item.id).order_by(Artifact.id.desc()))
    return {"id": item.id, "kind": item.kind, "title": item.user_title or item.title,
            "domain": domain.hostname, "description": item.user_description or item.description,
            "artwork_url": item.artwork_url, "duration": item.duration,
            "published_at": item.published_at,
            "downloaded": bool(artifact and Path(artifact.path).is_file()),
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
        raise HTTPException(502, "Source match operation is unavailable") from exc


@router.post("/sources/{source_id}/entries")
def source_entries(source_id: str, request: ResolveRequest, cursor: str | None = None,
                   limit: int = 50):
    source_manifest(source_id)
    try:
        with get_session() as session:
            token = connection_token(session, source_id, request.connection_id)
        return SourceGateway().entries(source_id, request.url, cursor=cursor, limit=limit,
            access_token=token)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Source enumeration is unavailable") from exc


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
        return source_runtime.install_bundled_updates()
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
def resolve(request: ResolveRequest):
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
            token = connection_token(session, source_id, request.connection_id)
        kwargs = {"access_token": token} if token else {}
        return gateway.resolve(source_id, request.url, **kwargs)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.info("Source %s could not resolve URL", source_id, exc_info=True)
        raise HTTPException(502, f"{source_id} could not resolve this URL; choose another Source explicitly if appropriate") from exc


@router.post("/import")
def import_media(request: ImportRequest):
    snapshot = request.snapshot
    # Re-resolve the original URL instead of trusting client-supplied metadata or identity.
    try:
        with get_session() as session:
            token = connection_token(session, snapshot.reference.source_id, request.connection_id)
        kwargs = {"access_token": token} if token else {}
        snapshot = SourceGateway().resolve(snapshot.reference.source_id, snapshot.reference.url, **kwargs)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Source could not verify this media") from exc
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
                       published_at=snapshot.published_at if "published_at" in snapshot.model_fields_set else _MISSING)
        session.flush()
        if snapshot.kind == "collection":
            for entry in snapshot.entries:
                child = _upsert(session, entry.reference, entry.kind, entry.title,
                                connection_id=connection_id,
                                published_at=entry.published_at if "published_at" in entry.model_fields_set else _MISSING)
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
                                connection_id=connection_id)
                child.parent_id = child.parent_id or item.id
                child.extra_type = extra.extra_type or "other"
                session.flush()
                membership = session.scalar(select(MovieExtraParent).where(
                    MovieExtraParent.movie_id == item.id, MovieExtraParent.extra_id == child.id))
                if not membership:
                    session.add(MovieExtraParent(movie_id=item.id, extra_id=child.id,
                        extra_type=child.extra_type))
        result = _serialize(session, item)
        session.commit()
        return result


@router.post("/library/{collection_id}/refresh")
def refresh_collection(collection_id: int):
    with get_session() as session:
        collection = session.get(MediaItem, collection_id)
        if not collection or collection.kind != "collection":
            raise HTTPException(404, "Collection not found")
        reference = _reference_for(session, collection_id)
        if not reference:
            raise HTTPException(409, "Collection has no available Source connection")
        source_id, url = reference.source_id, reference.url
        connection_id = reference.connection_id
        token = connection_token(session, source_id, connection_id)
    try:
        gateway = SourceGateway()
        snapshot = gateway.resolve(source_id, url, **({"access_token": token} if token else {}))
    except Exception as exc:
        raise HTTPException(502, "Collection Source is unavailable") from exc
    if snapshot.kind != "collection":
        raise HTTPException(409, "Source no longer identifies this URL as a collection")
    runtime_version = None
    try:
        runtime_version = command_for(source_id)[1]
    except (ValueError, RuntimeError):
        runtime_version = "configured"
    entries, cursor = [], None
    try:
        paged = next((m for m in gateway.manifests() if m.source_id == source_id), None)
        if paged and "enumerate_pages" in paged.capabilities:
            complete = False
            seen_cursors = set()
            # A bounded reconciliation never expands nested Collections implicitly.
            for _ in range(100):
                page = gateway.entries(source_id, url, cursor=cursor, limit=50, access_token=token)
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
            next_cursor=cursor, runtime_version=runtime_version)
    return _import_snapshot(snapshot, connection_id, runtime_version=runtime_version)


@router.get("/library")
def library():
    with get_session() as session:
        items = session.scalars(select(MediaItem).order_by(MediaItem.created_at.desc())).all()
        members = set(session.scalars(select(CollectionEntry.item_id)).all())
        return [_serialize(session, item) for item in items if item.id not in members and
                (item.kind != "movie_extra" or item.parent_id is None)]


@router.get("/home")
def home():
    with get_session() as session:
        progress = session.scalars(select(PlaybackProgress).where(
            PlaybackProgress.user_key == "admin", PlaybackProgress.completed.is_(False))
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
def playback_progress(item_id: int):
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        if not item or item.kind == "collection":
            raise HTTPException(404, "Playable media item not found")
        progress = session.scalar(select(PlaybackProgress).where(
            PlaybackProgress.user_key == "admin", PlaybackProgress.item_id == item_id))
        return {"seconds": progress.seconds if progress else 0,
                "completed": progress.completed if progress else False}


@router.put("/library/{item_id}/progress")
def save_playback_progress(item_id: int, data: PlaybackInput):
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        if not item or item.kind == "collection":
            raise HTTPException(404, "Playable media item not found")
        progress = session.scalar(select(PlaybackProgress).where(
            PlaybackProgress.user_key == "admin", PlaybackProgress.item_id == item_id))
        if not progress:
            progress = PlaybackProgress(user_key="admin", item_id=item_id)
            session.add(progress)
        progress.seconds, progress.completed = data.seconds, data.completed
        session.commit()
        return {"seconds": progress.seconds, "completed": progress.completed}


@router.get("/library/{item_id}")
def library_item(item_id: int):
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        if not item:
            raise HTTPException(404, "Media item not found")
        result = _serialize(session, item)
        if item.kind == "collection":
            entries = session.scalars(select(CollectionEntry).where(
                CollectionEntry.collection_id == item_id).order_by(CollectionEntry.position)).all()
            result["entries"] = [_serialize(session, session.get(MediaItem, e.item_id)) for e in entries]
        if item.kind == "movie":
            extras = session.scalars(select(MovieExtraParent).where(MovieExtraParent.movie_id == item_id)).all()
            result["extras"] = [_serialize(session, session.get(MediaItem, e.extra_id)) for e in extras]
        return result


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
        session.execute(delete(CollectionStreamProfile).where(CollectionStreamProfile.collection_id == item_id))
        session.execute(delete(CollectionDownloadProfile).where(CollectionDownloadProfile.collection_id == item_id))
        session.execute(delete(CollectionScan).where(CollectionScan.collection_id == item_id))
        session.execute(delete(CollectionEntry).where(or_(
            CollectionEntry.collection_id == item_id, CollectionEntry.item_id == item_id)))
        session.execute(delete(SourceReference).where(SourceReference.item_id == item_id))
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
        item.user_title = data.title.strip() if data.title and data.title.strip() else None
        item.user_description = data.description.strip() if data.description and data.description.strip() else None
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
                source_id = session.get(SourceReference, job.reference_id).source_id
            with _source_slots_lock:
                slot = _source_slots.setdefault(source_id, threading.BoundedSemaphore(1))
            with slot:
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
        item_id, source_id, url = job.item_id, reference.source_id, reference.url
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
            token = connection_token(session, source_id, connection_id)
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"job-{job_id}-", dir=root) as staging:
            _job_stage(job_id, "downloading")
            command = spec.get("source_command")
            gateway = SourceGateway({source_id: command}) if command else SourceGateway()
            kwargs = {"access_token": token} if token else {}
            result = gateway.download(source_id, url, staging,
                preferred_format=spec.get("preferred_format", "format_1080p"), job_id=job_id, **kwargs)
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
            job.state, job.active_key, job.error = (
                "canceled" if canceled else "failed", None,
                None if canceled else "The Source download or finalization failed")
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
            age = now - job.updated_at.replace(tzinfo=job.updated_at.tzinfo or timezone.utc)
            if age < timedelta(seconds=30 * (2 ** max(job.attempts - 1, 0))):
                continue
            key = f"{job.item_id}:{job.profile_id}"
            if session.scalar(select(AcquisitionJob.id).where(AcquisitionJob.active_key == key)):
                continue
            job.state, job.error = "queued", None
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
                   force: bool = False) -> tuple[int | None, str, bool]:
    """Freeze a Domain profile for one playable item; null means already satisfied."""
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        if not item or item.kind == "collection":
            raise HTTPException(404, "Playable media item not found")
        if not force:
            existing_artifact = session.scalar(select(Artifact).where(
                Artifact.item_id == item_id, Artifact.profile_id == profile_id).order_by(Artifact.id.desc()))
            if existing_artifact and Path(existing_artifact.path).is_file():
                return None, "available", False
        existing = session.scalar(select(AcquisitionJob).where(
            AcquisitionJob.active_key == f"{item_id}:{profile_id}"))
        if existing:
            return existing.id, existing.state, False
        reference = _reference_for(session, item_id)
        if not reference:
            raise HTTPException(409, "No Source reference is available")
        query = select(DomainLocalMediaProfile).where(
            DomainLocalMediaProfile.domain_id == item.domain_id,
            DomainLocalMediaProfile.enabled.is_(True))
        if profile_id is not None:
            query = query.where(DomainLocalMediaProfile.id == profile_id)
        profile = next((p for p in session.scalars(query).all() if item.kind in p.applicable_kinds), None)
        if not profile:
            raise HTTPException(409, "Create and select a Local Media Profile for this Domain and media type")
        domain = session.get(Domain, item.domain_id)
        gateway = SourceGateway()
        selected_command = gateway.commands.get(reference.source_id)
        try:
            runtime_version = command_for(reference.source_id)[1]
        except ValueError:
            runtime_version = "configured"
        spec = {"preferred_format": profile.preferred_format,
                "output_template": profile.output_template, "profile_id": profile.id,
                "profile_revision": profile.updated_at.isoformat() if profile.updated_at else None,
                "source_id": reference.source_id, "reference_id": reference.id,
                "source_command": selected_command, "runtime_version": runtime_version,
                "connection_id": reference.connection_id, "queued_at": datetime.now(timezone.utc).isoformat(),
                "values": {"domain": domain.hostname, "title": item.user_title or item.title,
                           "id": item.id, "upstream_id": reference.upstream_id,
                           "media_type": item.kind,
                           "collection": session.get(MediaItem, collection_id).user_title or session.get(MediaItem, collection_id).title if collection_id else ""}}
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
                return existing.id, existing.state, False
            raise
        return job.id, job.state, True


@router.post("/library/{item_id}/download")
def download_item(item_id: int, background: BackgroundTasks, request: DownloadRequest | None = None):
    job_id, state, created = queue_download(item_id, request.profile_id if request else None, force=True)
    if not created:
        return {"id": job_id, "state": state}
    background.add_task(_run_download, job_id)
    return {"id": job_id, "state": state}


@router.get("/jobs/{job_id}")
def job_status(job_id: int):
    with get_session() as session:
        job = session.get(AcquisitionJob, job_id)
        if not job:
            raise HTTPException(404, "Acquisition job not found")
        return {"id": job.id, "item_id": job.item_id, "state": job.state,
                "error": job.error, "attempts": job.attempts,
                "cancel_requested": job.cancel_requested, "profile_id": job.profile_id,
                "operation_id": job.operation_id, "progress": _JOB_PROGRESS.get(job.state, 0)}


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
        key = f"{job.item_id}:{job.profile_id}"
        if session.scalar(select(AcquisitionJob.id).where(AcquisitionJob.active_key == key)):
            raise HTTPException(409, "An acquisition is already active for this representation")
        job.state, job.error, job.cancel_requested = "queued", None, False
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


@router.get("/library/{item_id}/play/version/{filename}")
def play_version(item_id: int, filename: str):
    # A redirect binds subsequent range requests to the same immutable file,
    # even when a newer download is published for this item.
    if not re.fullmatch(rf"{item_id}-[0-9]+\.(?:mp4|mkv|webm|mp3|m4a|opus|ogg|wav|mov)", filename):
        raise HTTPException(404, "Representation not found")
    path = Path(get_settings().download_settings.download_root).resolve() / "vodloft" / filename
    if not path.is_file():
        raise HTTPException(404, "Representation not found")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
