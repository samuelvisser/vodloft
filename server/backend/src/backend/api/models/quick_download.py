from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import AliasPath, Field

from backend.api.models.base import RequestBase, ResponseBase, response_model_config
from backend.api.models.operations import TaskOperationAccepted, TaskOperationRead
from backend.api.models.source import ResolvedLinkAPIRead


class QuickDownloadChoiceAPI(RequestBase):
    kind: Literal["video", "audio"] = "video"
    quality: Optional[Literal[2160, 1440, 1080, 720, 480]] = None
    """A height in pixels; none is Best."""
    container: Literal["mp4", "mkv"] = "mp4"
    codec: Optional[Literal["h264", "h265", "vp9", "av1"]] = None
    """None is Auto."""
    audio_format: Literal["m4a", "mp3"] = "m4a"
    audio_bitrate: Optional[Literal[320, 192, 128]] = None
    embed_metadata: bool = True
    embed_artwork: bool = True


class QuickDownloadOptionsAPIRequest(RequestBase):
    url: str = Field(min_length=1, max_length=2048)
    source_key: Optional[str] = None


class QuickDownloadCodecAPIRead(ResponseBase):
    codec: str
    size_bytes: Optional[int] = None


class QuickDownloadVideoOptionAPIRead(ResponseBase):
    quality: Optional[int] = None
    size_bytes: Optional[int] = None
    codecs: list[QuickDownloadCodecAPIRead] = Field(default_factory=list)


class QuickDownloadAudioOptionAPIRead(ResponseBase):
    audio_format: Literal["m4a", "mp3"]
    bitrate: Optional[int] = None
    size_bytes: Optional[int] = None


class QuickDownloadOptionsAPIRead(ResponseBase):
    """What a link can be quick downloaded as. ``refused`` says why it cannot, with no options."""

    model_config = response_model_config(nested_source="options")

    link: ResolvedLinkAPIRead
    refused: Optional[str] = None
    format_choices: bool = False
    """The Source offers qualities, containers and codecs, not only Best MP4 and M4A."""
    containers: list[str] = Field(default_factory=list)
    videos: list[QuickDownloadVideoOptionAPIRead] = Field(default_factory=list)
    audio: list[QuickDownloadAudioOptionAPIRead] = Field(default_factory=list)
    duration: Optional[float] = None


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
