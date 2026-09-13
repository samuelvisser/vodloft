from __future__ import annotations

from datetime import date, datetime

from media_profiles import CollectionKind
from pydantic import BaseModel, ConfigDict, Field


class CollectionCreate(BaseModel):
    url: str
    kind: CollectionKind | None = None


class VideoCreate(BaseModel):
    url: str


class VideoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_url: str
    extractor: str
    extractor_id: str
    title: str
    description: str | None
    uploader: str | None
    channel: str | None
    duration: float | None
    upload_date: date | None
    thumbnail_url: str | None
    downloaded_path: str | None
    downloaded_format: str | None
    downloaded_at: datetime | None


class CollectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: CollectionKind
    source_url: str
    extractor: str
    extractor_id: str
    title: str
    description: str | None
    uploader: str | None
    channel: str | None
    thumbnail_url: str | None
    last_synced_at: datetime | None
    videos: list[VideoRead] = Field(default_factory=list)


class SourceInspection(BaseModel):
    kind: CollectionKind | str
    title: str
    extractor: str
    extractor_id: str
    url: str
    entry_count: int | None = None
