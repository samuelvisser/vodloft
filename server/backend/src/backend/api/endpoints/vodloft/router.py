"""Generic Add URL, library, acquisition and local playback prototype."""

import logging
import mimetypes
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.db import get_session
from backend.db.models.vodloft import (
    AcquisitionJob, Artifact, ArtifactPlacement, CollectionEntry, CollectionScan, Domain, FileFinalization, MediaItem, MovieExtraParent, SourceConnection, SourceDomain, SourceReference,
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vodloft", tags=["VodLoft library"])
_download_slots = threading.BoundedSemaphore(2)
_source_slots: dict[str, threading.BoundedSemaphore] = {}
_source_slots_lock = threading.Lock()


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


def _domain(session, hostname: str) -> Domain:
    hostname = hostname.rstrip(".").lower().encode("idna").decode("ascii")
    domain = session.scalar(select(Domain).where(Domain.hostname == hostname))
    if not domain:
        domain = Domain(hostname=hostname, display_name=hostname)
        session.add(domain)
        session.flush()
    return domain


def _upsert(session, reference: SourceMediaReference, kind: str, title: str,
            description: str | None = None, duration: float | None = None,
            artwork_url: str | None = None, connection_id: int | None = None) -> MediaItem:
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
        if description is not None:
            item.description = description
        if duration is not None:
            item.duration = duration
        if artwork_url is not None:
            item.artwork_url = artwork_url
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
                             description=description, duration=duration, artwork_url=artwork_url)
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
            "downloaded": bool(artifact and Path(artifact.path).is_file())}


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


@router.get("/sources/runtimes")
def source_runtimes():
    return source_runtime.status()


class SourceUpdatePolicyInput(BaseModel):
    automatic: bool = True
    pinned_version: str | None = None


@router.put("/sources/{source_id}/policy")
def source_update_policy(source_id: str, data: SourceUpdatePolicyInput):
    try:
        return source_runtime.set_policy(source_id, data.automatic, data.pinned_version)
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
    candidates = [request.source_id] if request.source_id else [s.source_id for s in gateway.manifests()]
    if not candidates:
        raise HTTPException(503, "No healthy Source runtime is installed")
    for source_id in candidates:
        try:
            with get_session() as session:
                token = connection_token(session, source_id, request.connection_id)
            kwargs = {"access_token": token} if token else {}
            return gateway.resolve(source_id, request.url, **kwargs)
        except ValueError:
            continue
        except Exception:
            logger.info("Source %s could not resolve URL", source_id, exc_info=True)
    raise HTTPException(422, "No installed Source could resolve this URL")


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


def _import_snapshot(snapshot: MediaSnapshot, connection_id: int | None = None) -> dict:
    with get_session() as session:
        item = _upsert(session, snapshot.reference, snapshot.kind, snapshot.title,
                       snapshot.description, snapshot.duration, snapshot.artwork_url, connection_id)
        session.flush()
        if snapshot.kind == "collection":
            for entry in snapshot.entries:
                child = _upsert(session, entry.reference, "video", entry.title,
                                connection_id=connection_id)
                session.flush()
                membership = session.scalar(select(CollectionEntry).where(
                    CollectionEntry.collection_id == item.id, CollectionEntry.item_id == child.id))
                if membership:
                    membership.position = entry.position
                else:
                    session.add(CollectionEntry(collection_id=item.id, item_id=child.id,
                        position=entry.position, group=entry.group,
                        episode_number=entry.episode_number))
            # An incomplete scan must never infer removal. This prototype leaves
            # old members in place even after a complete scan until policy exists.
            session.add(CollectionScan(collection_id=item.id, source_id=snapshot.reference.source_id,
                complete=snapshot.enumeration_complete, entry_count=len(snapshot.entries)))
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
        snapshot = SourceGateway().resolve(source_id, url, **({"access_token": token} if token else {}))
    except Exception as exc:
        raise HTTPException(502, "Collection Source is unavailable") from exc
    if snapshot.kind != "collection":
        raise HTTPException(409, "Source no longer identifies this URL as a collection")
    return _import_snapshot(snapshot, connection_id)


@router.get("/library")
def library():
    with get_session() as session:
        items = session.scalars(select(MediaItem).order_by(MediaItem.created_at.desc())).all()
        members = set(session.scalars(select(CollectionEntry.item_id)).all())
        return [_serialize(session, item) for item in items if item.id not in members and
                (item.kind != "movie_extra" or item.parent_id is None)]


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
    with _download_slots:
        with get_session() as session:
            job = session.get(AcquisitionJob, job_id)
            if not job:
                return
            source_id = session.get(SourceReference, job.reference_id).source_id
        with _source_slots_lock:
            slot = _source_slots.setdefault(source_id, threading.BoundedSemaphore(1))
        with slot:
            _execute_download(job_id)


def _execute_download(job_id: int) -> None:
    with get_session() as session:
        job = session.get(AcquisitionJob, job_id)
        if not job or job.state not in ("queued", "resolving", "downloading", "processing", "verifying", "finalizing"):
            return
        if job.cancel_requested:
            job.state, job.active_key = "canceled", None
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
        session.commit()


def recover_acquisition_jobs() -> None:
    """Resume jobs whose HTTP background task was interrupted by a restart."""
    with get_session() as session:
        jobs = session.scalars(select(AcquisitionJob).where(
            AcquisitionJob.state.in_(["queued", "resolving", "downloading", "processing", "verifying", "finalizing"]))).all()
        ids = [job.id for job in jobs]
        for job in jobs:
            if job.cancel_requested:
                job.state, job.active_key = "canceled", None
            else:
                job.state = "queued"
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
                "cancel_requested": job.cancel_requested, "profile_id": job.profile_id}


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
        session.commit()
    if not was_queued:
        cancel_running_job(job_id)
    return {"id": job_id, "state": "cancel_requested"}


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
