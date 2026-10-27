"""Store single videos that a Source describes."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import Video
from backend.types.media_types import MediaType
from backend.utils.helpers import generate_uuid
from sources import VideoDetails


def find_video(s: Session, source_key: str, slug: str) -> Optional[Video]:
    return (
        s.query(Video)
        .filter(Video.source_key == source_key, Video.slug == slug)
        .one_or_none()
    )


def apply_video_details(video: Video, details: VideoDetails) -> None:
    video.sharing_url = details.url
    video.title = details.title
    video.description = details.description
    video.duration = details.duration or 0.0
    video.author_name = details.author_name
    video.author_url = details.author_url
    video.published_at = details.published_at
    video.drm_protected = details.drm_protected
    video.needs_subscription = details.needs_subscription
    # Video thumbnails are landscape; they double as the page background.
    video.thumbnail_landscape_path = details.image_url
    video.background_image_path = details.image_url


def index_video(s: Session, source_key: str, details: VideoDetails) -> tuple[Video, bool]:
    """Store or refresh one video. Returns the video and whether it is new."""
    video = find_video(s, source_key, details.slug)
    created = video is None
    if video is None:
        video = Video(
            uuid=generate_uuid(),
            type=MediaType.VIDEO.value,
            source_key=source_key,
            slug=details.slug,
        )
        s.add(video)
    apply_video_details(video, details)
    s.flush()
    return video, created
