from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from config import get_settings
from controller.workers import queue_download, queue_sync, resolve_stream
from ytdlp_client import YtDlpClient

from backend.db import get_session
from backend.db.models import Collection, LocalMediaProfile, Video
from backend.schemas import (
    CollectionCreate,
    CollectionRead,
    SourceInspection,
    TaskRead,
    VideoCreate,
    VideoDownloadCreate,
    VideoRead,
)
from backend.schemas.tasks import task_read
from backend.services.library import add_collection, add_video, detect_collection_kind

router = APIRouter(prefix="/library", tags=["library"])


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


@router.post("/collections", response_model=CollectionRead, status_code=201)
def create_collection(payload: CollectionCreate, session: Session = Depends(get_session)):
    try:
        return add_collection(session, _client(), payload.url, payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/collections/{collection_id}/sync", response_model=TaskRead, status_code=202)
def sync_collection_route(collection_id: int, session: Session = Depends(get_session)):
    if session.get(Collection, collection_id) is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return task_read(queue_sync(collection_id))


@router.get("/videos", response_model=list[VideoRead])
def list_videos(standalone_only: bool = False, session: Session = Depends(get_session)):
    statement = select(Video).options(selectinload(Video.media_downloads))
    if standalone_only:
        statement = statement.where(Video.standalone.is_(True))
    statement = statement.order_by(Video.upload_date.desc().nullslast(), Video.id.desc())
    return list(session.scalars(statement))


@router.post("/videos", response_model=VideoRead, status_code=201)
def create_video(payload: VideoCreate, session: Session = Depends(get_session)):
    try:
        return add_video(session, _client(), payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/videos/{video_id}/download", response_model=TaskRead, status_code=202)
def start_download(
    video_id: int,
    payload: VideoDownloadCreate,
    session: Session = Depends(get_session),
):
    video = session.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    profile = session.get(LocalMediaProfile, payload.local_media_profile_id)
    if profile is None:
        raise HTTPException(status_code=422, detail="Local media profile not found")
    if video.standalone and profile.scope != "video":
        raise HTTPException(status_code=422, detail="Standalone videos require a video local media profile")
    try:
        return task_read(queue_download(video_id, profile.id))
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
        data = client.extract_collection(payload.url, flat=True)
    except ValueError:
        video = client.extract_video(payload.url)
        return SourceInspection(
            kind="video",
            title=video.title,
            extractor=video.extractor,
            extractor_id=video.extractor_id,
            url=video.webpage_url,
        )
    kind = detect_collection_kind(payload.url, data)
    return SourceInspection(
        kind=kind,
        title=data.title,
        extractor=data.extractor,
        extractor_id=data.extractor_id,
        url=data.webpage_url,
        entry_count=len(data.entries),
    )
