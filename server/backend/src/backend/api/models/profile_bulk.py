"""Changing or deleting many profiles of one table at once, from its bulk edit mode."""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import Field, model_validator

from backend.api.models.base import RequestBase, ResponseBase
from backend.types.download_profile_types import UpgradeRepeat
from backend.types.local_media_profile_types import (
    LocalMediaProfileMetadataMode,
    LocalMediaProfileStorageMode,
    LocalMediaProfileThumbnailMode,
)

MAX_BULK_PROFILES = 10_000


class ProfileIdsRead(ResponseBase):
    """Every profile the table's filters match, for its Select all."""

    ids: list[int]


class BulkSelectionIn(RequestBase):
    ids: list[int] = Field(min_length=1, max_length=MAX_BULK_PROFILES)


class BulkChangesIn(RequestBase):
    """Only the settings that are sent change; a setting cannot be sent empty."""

    @model_validator(mode="after")
    def _something_to_change(self):
        if not self.model_fields_set:
            raise ValueError("Choose a setting to change")
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"Choose a value for {name}")
        return self


class DownloadProfileBulkChangesIn(BulkChangesIn):
    enable_profile: bool | None = None
    local_media_profile_id: int | None = None
    download_with_countdown: bool | None = None
    upgrade_check: bool | None = None
    upgrade_repeat: UpgradeRepeat | None = None
    sponsorblock_enabled: bool | None = None


class StreamProfileBulkChangesIn(BulkChangesIn):
    enable_profile: bool | None = None
    use_downloads: bool | None = None
    use_source_stream: bool | None = None
    max_items: int | None = Field(default=None, ge=0)
    proxy_source_stream: bool | None = None
    stream_live_episodes: bool | None = None


class LocalMediaProfileBulkChangesIn(BulkChangesIn):
    download_mode: LocalMediaProfileStorageMode | None = None
    thumbnail_mode: LocalMediaProfileThumbnailMode | None = None
    metadata_mode: LocalMediaProfileMetadataMode | None = None


ChangesT = TypeVar("ChangesT", bound=BulkChangesIn)


class BulkChangeIn(BulkSelectionIn, Generic[ChangesT]):
    changes: ChangesT


class BulkSkippedRead(ResponseBase):
    id: int
    name: str
    reason: str


class BulkResultRead(ResponseBase):
    """How many profiles changed, and the ones left as they were with why."""

    done: int
    skipped: list[BulkSkippedRead]


class BulkValueCountRead(ResponseBase):
    value: str | int | bool | None
    count: int


class BulkFieldSummaryRead(ResponseBase):
    offered: int
    """How many of the profiles have the setting at all, such as SponsorBlock only on YouTube."""
    values: list[BulkValueCountRead]
    """What the profiles that have it are set to now, most common first."""


class BulkSummaryRead(ResponseBase):
    count: int
    fields: dict[str, BulkFieldSummaryRead]
    """By the setting's name as the changes send it."""
