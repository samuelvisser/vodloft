from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import AliasPath, Field

from backend.api.models.base import RequestBase, ResponseBase
from task_manager.scheduler.operation_control import OPERATION_CANCELABLE_CONTEXT_KEY


class OperationsSeenRequest(RequestBase):
    """Operations whose finished state a browser has shown and refreshed its data for."""

    operation_ids: list[str] = Field(min_length=1, max_length=500)


class TaskOperationAccepted(ResponseBase):
    queued: bool
    operation_id: str


class MediaDownloadOperationAccepted(TaskOperationAccepted):
    media_download_id: int
    queue_positions: dict[int, int] | None = None


class MediaDownloadBulkOperationAccepted(TaskOperationAccepted):
    downloads_queued: int


class MovieRedownloadOperationAccepted(TaskOperationAccepted):
    downloads_queued: int


class MovieDeleteDownloadsOperationAccepted(TaskOperationAccepted):
    downloads_queued: int


class CollectionDownloadAllOperationAccepted(TaskOperationAccepted):
    episodes_queued: int


class CollectionMetadataOperationAccepted(TaskOperationAccepted):
    episodes_queued: int


class CollectionFileRenameOperationAccepted(TaskOperationAccepted):
    episodes_queued: int
    local_media_profiles_queued: int


class LocalMediaProfileFileRenameOperationAccepted(TaskOperationAccepted):
    episodes_queued: int


class LocalMediaProfileMaintenanceOperationAccepted(TaskOperationAccepted):
    downloads_queued: int


class LocalMediaProfileDeleteDownloadsOperationAccepted(
    LocalMediaProfileMaintenanceOperationAccepted
):
    download_profiles_disabled: int


class DownloadProfileDeleteOutOfScopeOperationAccepted(TaskOperationAccepted):
    downloads_queued: int


class LocalMediaProfileRedownloadOperationAccepted(
    LocalMediaProfileMaintenanceOperationAccepted
):
    pass


class _CollectionDownloadMaintenanceOperationAccepted(TaskOperationAccepted):
    local_media_profiles_queued: int


class CollectionDeleteDownloadsOperationAccepted(_CollectionDownloadMaintenanceOperationAccepted):
    download_profiles_disabled: int


class CollectionRedownloadOperationAccepted(_CollectionDownloadMaintenanceOperationAccepted):
    pass


class EpisodeMetadataOperationAccepted(TaskOperationAccepted):
    episode_id: int


class TaskOperationRead(ResponseBase):
    id: str
    kind: str
    source: str
    resource_type: str
    resource_id: Optional[int]
    title: str
    status: str
    progress: Optional[int]
    completion_progress: Optional[int]
    progress_current: int
    progress_total: int
    message: Optional[str]
    result: Optional[dict[str, Any]]
    context: Optional[dict[str, Any]]
    progress_meta: Optional[dict[str, Any]] = None
    # Whether a person may cancel it, as its definition said; every place that offers to cancel it asks this.
    cancelable: bool = Field(default=True, validation_alias=AliasPath("context", OPERATION_CANCELABLE_CONTEXT_KEY))
    error: Optional[str]
    notification_seen_at: Optional[datetime]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class LocalMediaProfileMoveEpisodesOperationAccepted(TaskOperationAccepted):
    episodes_queued: int
    collections_queued: int
    download_profiles_paused: int


class CollectionMetadataRewriteOperationAccepted(TaskOperationAccepted):
    local_media_profiles_queued: int
