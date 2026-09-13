from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from task_manager import emit_event
from ytdlp_client import YtDlpClient

from config import get_settings
from controller.workers import queue_download, queue_sync, resolve_stream
from backend.db import get_session
from backend.db.models import Collection, LocalMediaProfile, MediaDownload, TaskRun, Video, collection_videos
from backend.schemas import CollectionCreate, CollectionRead, SourceInspection, VideoCreate, VideoDownloadCreate, VideoRead
from backend.schemas.tasks import TaskRunRead, task_run_read
from backend.services.library import add_collection, add_video, detect_collection_kind

router = APIRouter(prefix="/library", tags=["library"])


_ACTIVE_TASK_STATUSES = {"scheduled", "queued", "running", "retry_scheduled"}
_ACTIVE_DOWNLOAD_STATUSES = {"queued", "downloading"}


def _ensure_resource_idle(session: Session, resource_type: str, resource_id: int) -> None:
    active_run = session.scalar(
        select(TaskRun.id)
        .where(
            TaskRun.resource_type == resource_type,
            TaskRun.resource_id == resource_id,
            TaskRun.status.in_(_ACTIVE_TASK_STATUSES),
        )
        .limit(1)
    )
    if active_run is not None:
        raise HTTPException(status_code=409, detail="Resource still has active background work")


def _ensure_video_idle(session: Session, video_id: int) -> None:
    _ensure_resource_idle(session, "video", video_id)
    active_download = session.scalar(
        select(MediaDownload.id)
        .where(
            MediaDownload.video_id == video_id,
            MediaDownload.status.in_(_ACTIVE_DOWNLOAD_STATUSES),
        )
        .limit(1)
    )
    if active_download is not None:
        raise HTTPException(status_code=409, detail="Video still has an active download")


def _client() -> YtDlpClient:
    return YtDlpClient(get_settings().yt_dlp.options)


@router.get("/collections", response_model=list[CollectionRead])
def list_collections(session: Session = Depends(get_session)):
    statement = (
        select(Collection)
        .options(selectinload(Collection.videos).selectinload(Video.media_downloads))
        .order_by(Collection.title)
    )
    return list(session.scalars(statement).unique())


@router.get("/collections/{collection_id}", response_model=CollectionRead)
def get_collection(collection_id: int, session: Session = Depends(get_session)):
    statement = (
        select(Collection)
        .where(Collection.id == collection_id)
        .options(selectinload(Collection.videos).selectinload(Video.media_downloads))
    )
    collection = session.scalar(statement)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


@router.post("/collections", response_model=CollectionRead, status_code=201)
def create_collection(payload: CollectionCreate, session: Session = Depends(get_session)):
    try:
        collection = add_collection(session, _client(), payload.url, payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    emit_event("collection.added", resource_type="collection", resource_id=collection.id)
    return collection


@router.post("/collections/{collection_id}/sync", response_model=TaskRunRead, status_code=202)
def sync_collection_route(collection_id: int, session: Session = Depends(get_session)):
    if session.get(Collection, collection_id) is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return task_run_read(queue_sync(collection_id))


@router.delete("/collections/{collection_id}", status_code=204)
def delete_collection(collection_id: int, session: Session = Depends(get_session)):
    collection = session.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    _ensure_resource_idle(session, "collection", collection_id)
    candidate_video_ids = [video.id for video in collection.videos]
    for video in collection.videos:
        if video.standalone:
            continue
        memberships = session.scalar(
            select(func.count()).select_from(collection_videos).where(collection_videos.c.video_id == video.id)
        )
        if int(memberships or 0) <= 1:
            _ensure_video_idle(session, video.id)
    session.delete(collection)
    session.flush()
    for video_id in candidate_video_ids:
        video = session.get(Video, video_id)
        if video is None or video.standalone:
            continue
        memberships = session.scalar(select(func.count()).select_from(collection_videos).where(collection_videos.c.video_id == video_id))
        if not memberships:
            session.delete(video)
    session.commit()
    return Response(status_code=204)


@router.get("/videos", response_model=list[VideoRead])
def list_videos(standalone_only: bool = False, session: Session = Depends(get_session)):
    statement = select(Video).options(selectinload(Video.media_downloads))
    if standalone_only:
        statement = statement.where(Video.standalone.is_(True))
    statement = statement.order_by(Video.upload_date.desc().nullslast(), Video.id.desc())
    return list(session.scalars(statement))


@router.get("/videos/{video_id}", response_model=VideoRead)
def get_video(video_id: int, session: Session = Depends(get_session)):
    video = session.scalar(select(Video).where(Video.id == video_id).options(selectinload(Video.media_downloads)))
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@router.post("/videos", response_model=VideoRead, status_code=201)
def create_video(payload: VideoCreate, session: Session = Depends(get_session)):
    try:
        video = add_video(session, _client(), payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    emit_event("video.added", resource_type="video", resource_id=video.id)
    return video


@router.delete("/videos/{video_id}", status_code=204)
def delete_video(video_id: int, session: Session = Depends(get_session)):
    video = session.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    _ensure_video_idle(session, video_id)
    video.standalone = False
    memberships = session.scalar(select(func.count()).select_from(collection_videos).where(collection_videos.c.video_id == video_id))
    if not memberships:
        session.delete(video)
    session.commit()
    return Response(status_code=204)


@router.post("/videos/{video_id}/download", response_model=TaskRunRead, status_code=202)
def start_download(video_id: int, payload: VideoDownloadCreate, session: Session = Depends(get_session)):
    video = session.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    profile = session.get(LocalMediaProfile, payload.local_media_profile_id)
    if profile is None:
        raise HTTPException(status_code=422, detail="Local media profile not found")
    if video.standalone and profile.scope != "video":
        raise HTTPException(status_code=422, detail="Standalone videos require a video local media profile")
    try:
        return task_run_read(queue_download(video_id, profile.id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/videos/{video_id}/stream")
def get_stream(video_id: int, profile_id: int):
    try:
        return resolve_stream(video_id, profile_id).model_dump()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/inspect", response_model=SourceInspection)
def inspect_source(payload: VideoCreate):
    client = _client()
    try:
        data = client.extract_collection(payload.url, flat=True, max_entries=1)
    except ValueError:
        video = client.extract_video(payload.url)
        return SourceInspection(kind="video", title=video.title, extractor=video.extractor, extractor_id=video.extractor_id, url=video.webpage_url)
    kind = detect_collection_kind(payload.url, data)
    return SourceInspection(
        kind=kind,
        title=data.title,
        extractor=data.extractor,
        extractor_id=data.extractor_id,
        url=data.webpage_url,
        entry_count=None,
    )
