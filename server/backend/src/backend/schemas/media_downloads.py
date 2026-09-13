from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MediaDownloadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    video_id: int
    local_media_profile_id: int
    status: str
    file_path: str | None
    downloaded_bytes: int | None
    format_downloaded: str | None
    error: str | None
    downloaded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class VideoDownloadCreate(BaseModel):
    local_media_profile_id: int
