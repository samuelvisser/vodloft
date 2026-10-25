from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.api.models.video import VideoAPIRead
from backend.db.models import Video
from config.network import is_no_internet_error
from sources import Feature, Source, UnknownSourceError, VideoDetails, get_source


def video_source(source_key: str) -> Source:
    try:
        source = get_source(source_key)
    except UnknownSourceError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown Source '{source_key}'") from exc
    if not source.has(Feature.VIDEOS):
        raise HTTPException(status_code=422, detail=f"{source.name} has no single videos")
    return source


def fetch_video_details(source: Source, url: str) -> VideoDetails:
    """Ask the Source about a video. Call it outside a database transaction."""
    try:
        return source.video_details(url)
    except Exception as exc:
        if is_no_internet_error(exc):
            raise
        raise HTTPException(status_code=502, detail=f"{source.name} could not look up this video: {exc}") from exc


def get_video_record(s: Session, video_id: int) -> Video:
    video: Optional[Video] = s.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


def get_videos_list(s: Session) -> list[VideoAPIRead]:
    items = (
        s.query(Video)
        .order_by(Video.published_at.desc().nulls_last(), Video.id.desc())
        .all()
    )
    return [VideoAPIRead.model_validate(item) for item in items]


def get_video(s: Session, video_id: int) -> VideoAPIRead:
    return VideoAPIRead.model_validate(get_video_record(s, video_id))


def delete_video(s: Session, video_id: int) -> VideoAPIRead:
    video = get_video_record(s, video_id)
    payload = VideoAPIRead.model_validate(video)
    s.delete(video)
    s.flush()
    return payload
