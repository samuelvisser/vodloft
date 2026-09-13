from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExtractedVideo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    extractor: str
    extractor_id: str
    webpage_url: str
    title: str
    description: str | None = None
    uploader: str | None = None
    uploader_id: str | None = None
    channel: str | None = None
    channel_id: str | None = None
    duration: float | None = None
    upload_date: date | None = None
    thumbnail_url: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)


class ExtractedCollection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    extractor: str
    extractor_id: str
    webpage_url: str
    title: str
    description: str | None = None
    uploader: str | None = None
    uploader_id: str | None = None
    channel: str | None = None
    channel_id: str | None = None
    playlist_id: str | None = None
    thumbnail_url: str | None = None
    entries: list[ExtractedVideo] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)


class DownloadOptions(BaseModel):
    output_template: str
    format_selector: str | None = None
    merge_output_format: str | None = None
    audio_format: str | None = None
    write_subtitles: bool = False
    embed_metadata: bool = True
    embed_thumbnail: bool = False
    additional_options: dict[str, Any] = Field(default_factory=dict)


class DownloadResult(BaseModel):
    extractor: str
    extractor_id: str
    title: str
    filepath: str | None = None
    ext: str | None = None
    format_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)


class StreamTarget(BaseModel):
    url: str
    format_id: str | None = None
    ext: str | None = None
    protocol: str | None = None
    vcodec: str | None = None
    acodec: str | None = None
    http_headers: dict[str, str] = Field(default_factory=dict)
