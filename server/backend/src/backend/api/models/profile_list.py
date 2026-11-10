"""The filters the profile tables send with each page request."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ProfileStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class FormatKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"


class StreamsFrom(StrEnum):
    DOWNLOADS = "downloads"
    SOURCE = "source"


class UsedFor(StrEnum):
    PODCAST = "podcast"
    SERIES = "series"
    MOVIE = "movie"
    VIDEO = "video"


class StorageUse(StrEnum):
    FILES = "files"
    EMPTY = "empty"


class _ProfileListQuery(BaseModel):
    """An empty list leaves that filter off; several values match any of them."""

    model_config = ConfigDict(extra="forbid")

    cursor: str | None = Field(default=None, max_length=2048, description="Continues the list after an earlier page")
    limit: int = Field(default=50, ge=1, le=200)
    search: str = Field(default="", max_length=200, description="Words that must all appear")
    format: list[FormatKind] = Field(default_factory=list)


class DownloadProfileListQuery(_ProfileListQuery):
    site: list[str] = Field(default_factory=list, max_length=50, description="Keys of the Sites the collection is on")
    status: list[ProfileStatus] = Field(default_factory=list)
    local_media_profile_id: int | None = Field(default=None, ge=1)


class StreamProfileListQuery(_ProfileListQuery):
    site: list[str] = Field(default_factory=list, max_length=50, description="Keys of the Sites the collection is on")
    status: list[ProfileStatus] = Field(default_factory=list)
    streams_from: list[StreamsFrom] = Field(default_factory=list)


class LocalMediaProfileListQuery(_ProfileListQuery):
    site: list[str] = Field(default_factory=list, max_length=50, description="Keys of the Sites the profile is offered for")
    used_for: list[UsedFor] = Field(default_factory=list)
    storage: list[StorageUse] = Field(default_factory=list)
