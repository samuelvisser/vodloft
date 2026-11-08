from datetime import datetime
from typing import Optional

from pydantic import AliasPath, Field

from backend.api.models.base import RequestBase, ResponseBase, response_model_config
from backend.api.models.source import SourcedResponse
from backend.api.models.pagination import CursorPageRead
from backend.types.download_profile_types import MediaDownloadArtifactStatus


# ---------- Strict input (create/update) ----------
class _EpisodeDownloadDelayRequest(RequestBase):
    """Controls for an explicit episode download requested before its safety deadline."""

    redownload_when_delay_passed: bool = False
    schedule_for_delay: bool = False


class EpisodeDownloadAPICreate(_EpisodeDownloadDelayRequest):
    """Request body for starting an episode download for a Local Media Profile."""

    local_media_profile_id: int
    redownload_when_final: bool = False


class MediaDownloadRetryAPIRequest(_EpisodeDownloadDelayRequest):
    """Optional controls for an explicit retry/re-download request."""


class MediaDownloadAPICreate(RequestBase):
    """Request body for starting a download of a movie, movie extra or video for a Local Media Profile."""

    local_media_profile_id: int


class MediaDownloadAPIUpdate(RequestBase):
    """Update persistent artifact metadata only."""

    file_path: str


class MediaDownloadKeptAPIRequest(RequestBase):
    """Keep an episode's download from retention, or let retention delete it again."""

    kept: bool


class MediaDownloadBulkActionAPIRequest(RequestBase):
    """Exact download rows selected by a Downloads-page bulk action."""

    media_download_ids: list[int]


class MediaDownloadAssetAPIRead(ResponseBase):
    asset_key: str
    kind: str
    path: str
    suffix: str
    size_bytes: int | None
    fingerprint: str | None


class SponsorSegmentAPIRead(ResponseBase):
    """A SponsorBlock segment of the video as published, in seconds, and what the download did with it."""

    category: str
    start: float
    end: float
    action: str


# ---------- Persistent artifact output ----------
class _MediaDownloadAPIBaseOut(ResponseBase):
    model_config = response_model_config(nested_source="download")

    id: int
    type: str
    media_item_id: int
    local_media_profile_id: int
    file_path: str
    thumbnail_path: Optional[str] = None
    nfo_path: Optional[str] = None
    assets: list[MediaDownloadAssetAPIRead] = Field(default_factory=list)
    artifact_status: MediaDownloadArtifactStatus | str
    artifact_error: Optional[str]
    artifact_size_bytes: Optional[int]
    automatic_retry_suppressed: bool
    downloaded_bytes: Optional[int]
    format_downloaded: Optional[str]
    sponsorblock_segments: Optional[list[SponsorSegmentAPIRead]] = None
    """None when SponsorBlock was not asked; empty when it had no segments."""
    downloaded_at: Optional[datetime]
    redownload_when_final: Optional[bool] = None
    kept: Optional[bool] = None
    """Kept by hand: retention never deletes it. Only episodes have it."""
    video_height: Optional[int] = None
    video_codec: Optional[str] = None
    upgrade_check_at: Optional[datetime] = None
    """When the upgrade check looks for a better version next. Only episodes have it."""
    upgrade_result: Optional[str] = None
    """What the last upgrade check found: upgraded or checked. Only episodes have it."""


class MediaDownloadAPIRead(_MediaDownloadAPIBaseOut):
    """Persistent media artifact state. It never contains live task progress."""

    created_at: datetime
    updated_at: datetime


class MediaDownloadAPIReadView(SourcedResponse, MediaDownloadAPIRead):
    """Persistent artifact context plus the latest canonical TaskRun facts."""

    source_key: str = Field(validation_alias=AliasPath("media", "source_key"))
    media_slug: Optional[str] = Field(default=None, validation_alias=AliasPath("media", "slug"))
    media_title: Optional[str] = Field(default=None, validation_alias=AliasPath("media", "title"))
    episode_slug: Optional[str] = Field(default=None, validation_alias=AliasPath("episode", "slug"))
    episode_title: Optional[str] = Field(default=None, validation_alias=AliasPath("episode", "title"))
    episode_identifier: Optional[str] = Field(
        default=None,
        validation_alias=AliasPath("episode", "episode_identifier"),
    )
    collection_slug: Optional[str] = Field(default=None, validation_alias=AliasPath("collection", "slug"))
    collection_title: Optional[str] = Field(default=None, validation_alias=AliasPath("collection", "title"))
    movie_slug: Optional[str] = Field(default=None, validation_alias=AliasPath("movie", "slug"))
    movie_title: Optional[str] = Field(default=None, validation_alias=AliasPath("movie", "title"))
    movie_extra_type: Optional[str] = Field(
        default=None,
        validation_alias=AliasPath("movie_extra", "movie_extra_type"),
    )
    local_media_profile_name: Optional[str] = Field(
        default=None,
        validation_alias=AliasPath("profile", "name"),
    )
    preferred_format: Optional[str] = Field(
        default=None,
        validation_alias=AliasPath("profile", "preferred_format"),
    )
    downloaded_publish_status: Optional[str] = Field(
        default=None,
        validation_alias=AliasPath("download", "downloaded_publish_status"),
    )

    queue_position: Optional[int] = None
    latest_task_status: Optional[str] = Field(
        default=None,
        validation_alias=AliasPath("latest_run", "status"),
    )
    latest_task_error: Optional[str] = Field(
        default=None,
        validation_alias=AliasPath("latest_run", "last_error"),
    )
    latest_task_is_redownload: Optional[bool] = None
    latest_task_started_at: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasPath("latest_run", "started_at"),
    )
    latest_task_finished_at: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasPath("latest_run", "finished_at"),
    )

class MediaDownloadPageRead(CursorPageRead[MediaDownloadAPIReadView]):
    """One deterministic cursor page of the shared media-download collection."""

    total: int
    revision: str
    facets: dict[str, int] = Field(default_factory=dict)
    actions: dict[str, int] = Field(default_factory=dict)



class DownloadedLocalMediaProfileAPIRead(ResponseBase):
    """A Local Media Profile that holds downloads of a Collection's episodes."""

    id: int
    name: str
    preferred_format: Optional[str] = None
