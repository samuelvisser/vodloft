from __future__ import annotations

from media_profiles import MediaKind
from pydantic import BaseModel, ConfigDict


class LocalMediaProfileCreate(BaseModel):
    name: str
    media_kind: MediaKind = MediaKind.VIDEO
    output_template: str = "/downloads/%(uploader)s/%(title)s [%(id)s].%(ext)s"


class LocalMediaProfileRead(LocalMediaProfileCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class DownloadProfileCreate(BaseModel):
    name: str
    local_media_profile_id: int
    format_selector: str = "bestvideo*+bestaudio/best"
    merge_output_format: str | None = None
    audio_format: str | None = None
    write_subtitles: bool = False
    embed_metadata: bool = True
    embed_thumbnail: bool = False


class DownloadProfileRead(DownloadProfileCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class StreamProfileCreate(BaseModel):
    name: str
    format_selector: str = "best[protocol^=http][vcodec!=none][acodec!=none]/best"


class StreamProfileRead(StreamProfileCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
