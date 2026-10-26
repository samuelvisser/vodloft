from fastapi import APIRouter, status

from backend.api.models.media_download import MediaDownloadAPICreate
from backend.api.models.operations import MediaDownloadOperationAccepted
from backend.api.models.video import VideoAPICreate, VideoAPIRead
from backend.app import db_session
from backend.services.videos import apply_video_details, index_video
from task_manager.scheduler.types import OperationSource
from task_manager.tasks.media_download_operations import (
    create_media_download_operation,
    dispatch_queued_media_download_operations,
)

from ..media_downloads.service import create_video_download
from .service import (
    delete_video,
    fetch_video_details,
    get_video,
    get_video_record,
    get_videos_list,
    video_source,
)

router = APIRouter(prefix="/videos", tags=["Videos"])


@router.get("", response_model=list[VideoAPIRead])
def video_list():
    with db_session() as s:
        return get_videos_list(s)


@router.post("", response_model=VideoAPIRead, status_code=status.HTTP_201_CREATED)
def video_create(body: VideoAPICreate):
    """Add a single video by its link, or refresh it when it is already added."""
    source = video_source(body.source_key)
    details = fetch_video_details(source, body.url)
    with db_session() as s:
        try:
            video, _ = index_video(s, source.id, details)
            payload = VideoAPIRead.model_validate(video)
            s.commit()
            return payload
        except Exception:
            s.rollback()
            raise


@router.get("/{video_id}", response_model=VideoAPIRead)
def video_detail(video_id: int):
    with db_session() as s:
        return get_video(s, video_id)


@router.post("/{video_id}/refresh", response_model=VideoAPIRead)
def video_refresh(video_id: int):
    """Look the video up again at its Source and store what changed."""
    with db_session() as s:
        video = get_video_record(s, video_id)
        source_key, url = video.source_key, video.sharing_url
    details = fetch_video_details(video_source(source_key), url)
    with db_session() as s:
        try:
            video = get_video_record(s, video_id)
            apply_video_details(video, details)
            s.flush()
            payload = VideoAPIRead.model_validate(video)
            s.commit()
            return payload
        except Exception:
            s.rollback()
            raise


@router.post(
    "/{video_id}/downloads",
    response_model=MediaDownloadOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def video_download_create(video_id: int, body: MediaDownloadAPICreate):
    """Persist a video artifact target and start it as a generic UI operation."""
    with db_session() as s:
        try:
            download = create_video_download(s, get_video_record(s, video_id), body)
            operation = create_media_download_operation(s, download, source=OperationSource.UI)
            dispatch_queued_media_download_operations(s)
            result = {
                "queued": True,
                "operation_id": operation.id,
                "media_download_id": download.id,
            }
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.delete("/{video_id}", response_model=VideoAPIRead)
def video_delete(video_id: int):
    with db_session() as s:
        try:
            result = delete_video(s, video_id)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise
