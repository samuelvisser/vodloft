from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import AliasPath, Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.api.models.operations import TaskOperationAccepted, TaskOperationRead


class QuickDownloadChoiceAPI(RequestBase):
    kind: Literal["video", "audio"] = "video"
    container: Literal["mp4", "mkv"] = "mp4"
    audio_format: Literal["m4a"] = "m4a"
    embed_metadata: bool = True
    embed_artwork: bool = True


class QuickDownloadAPICreate(RequestBase):
    url: str = Field(min_length=1, max_length=2048)
    # Ask only this Source, when the user picked one of several that claim the link.
    source_key: Optional[str] = None
    choice: QuickDownloadChoiceAPI = Field(default_factory=QuickDownloadChoiceAPI)


class QuickDownloadOperationAccepted(TaskOperationAccepted):
    quick_download_id: str


class QuickDownloadAPIRead(ResponseBase):
    """A file that is ready to download, as its manifest describes it."""

    id: str
    title: str
    file_name: str
    size_bytes: int
    format: str
    state: Literal["ready", "delivered"]
    created_at: datetime
    expires_at: datetime
    delivered_at: Optional[datetime] = None
    source_key: Optional[str] = Field(default=None, validation_alias=AliasPath("details", "source_key"))
    source_name: Optional[str] = Field(default=None, validation_alias=AliasPath("details", "source_name"))
    url: Optional[str] = Field(default=None, validation_alias=AliasPath("details", "url"))
    kind: Optional[str] = Field(default=None, validation_alias=AliasPath("details", "kind"))


class QuickDownloadsAPIRead(ResponseBase):
    active: list[TaskOperationRead]
    """Quick downloads still queued or working, as their operations."""
    ready: list[QuickDownloadAPIRead]
    """Files waiting to be downloaded, newest first."""
