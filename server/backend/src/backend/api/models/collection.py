from __future__ import annotations

from typing import Literal, Optional, Union
from datetime import date, datetime

from pydantic import AliasChoices, AliasPath, computed_field, Field, ValidationInfo, field_validator, model_validator

from backend.api.models.base import RequestBase, ResponseBase, response_model_config
from backend.api.models.custom_metadata import CustomMetadataResponseBase
from backend.api.models.source import SiteAPIRead, SourcedResponse
from backend.types.dailywire_user_info import DwMembershipLevel
from backend.types.collection_types import CheckFrequency, CollectionType, CookiesMode, EpisodeIdentifier
from config.settings.cron_validation import CronExpressionError, validate_cron_expression
from backend.types.download_profile_types import EpisodeTagKey
from backend.utils.helpers import generate_uuid
from backend.api.models.source import checked_ytdlp_options
from sources.ytdlp_options import MAX_OPTIONS_LENGTH


# ---------- Strict input (create/update) ----------
class _CollectionAPIBaseIn(RequestBase):
    """Fields for requests: validate here if needed."""

    title: str
    description: Optional[str] = None
    sharing_url: str
    membership_level: str
    author_name: str
    author_headshot_path: Optional[str] = None
    background_image_path: Optional[str] = None
    logo_image_path: Optional[str] = None
    thumbnail_landscape_path: Optional[str] = None
    thumbnail_portrait_path: Optional[str] = None
    thumbnail_square_path: Optional[str] = None


class CollectionAPICreate(_CollectionAPIBaseIn):
    """Request body for creating a collection."""

    slug: str
    source_key: str = Field(min_length=1)
    membership_level: DwMembershipLevel
    type: CollectionType
    episode_identifier: EpisodeIdentifier
    author_slug: str

    @computed_field(return_type=str)
    @property
    def uuid(self) -> str:
        return generate_uuid()


class CollectionAPIUpdate(_CollectionAPIBaseIn):
    """Request body for updating a collection.

    Collections from a Source without membership levels leave ``membership_level`` out.
    """

    membership_level: Optional[str] = None
    ytdlp_options: Optional[str] = Field(default=None, max_length=MAX_OPTIONS_LENGTH)
    """Your own yt-dlp options for this Collection; left out, they stay as they are."""

    cookies_mode: Optional[CookiesMode] = None
    check_frequency: Optional[CheckFrequency] = None
    check_cron: Optional[str] = Field(default=None, validate_default=True)
    """The Collection's own schedule, with ``check_frequency`` own."""

    @field_validator("ytdlp_options")
    @classmethod
    def _validate_ytdlp_options(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else checked_ytdlp_options(value)

    @field_validator("check_cron")
    @classmethod
    def _validate_check_cron(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        if value is None or not value.strip():
            if info.data.get("check_frequency") == CheckFrequency.OWN:
                raise ValueError("Enter the schedule to check this Collection on")
            return None
        value = " ".join(value.split())
        try:
            validate_cron_expression(value)
        except CronExpressionError as exc:
            raise ValueError(str(exc)) from exc
        return value


class CollectionCheckSuggestionAPIRead(ResponseBase):
    suggestion: Optional[str] = None


class CollectionFileRenameAPIRequest(RequestBase):
    """Select one Local Media Profile, or every profile with existing episode media."""

    local_media_profile_id: Optional[int] = Field(default=None, gt=0)


class CollectionDownloadAllAPIRequest(RequestBase):
    """Queue indexed episodes for one Local Media Profile and a collection-specific filter."""

    local_media_profile_id: int = Field(gt=0)
    season_ids: list[int] = Field(default_factory=list)
    episode_types: list[EpisodeTagKey] = Field(default_factory=list)
    download_days_in_past: int = Field(default=0, ge=0)
    download_episode_count: int = Field(default=0, ge=0)
    download_starting_from: date | None = None

    @model_validator(mode="after")
    def validate_podcast_limits(self):
        if self.download_days_in_past and self.download_episode_count:
            raise ValueError("Choose either a date limit or an episode-count limit, not both")
        if self.download_starting_from is not None and (
            self.download_days_in_past or self.download_episode_count
        ):
            raise ValueError("Download starting from can only be used when Limit by is set to No limits")
        return self


class _CollectionDownloadMaintenanceAPIRequest(RequestBase):
    """Scope collection download maintenance to selected profiles and older episodes."""

    local_media_profile_id: Optional[int] = Field(default=None, gt=0)
    delete_older_than: Literal["all", "days", "latest_downloads"] = "all"
    delete_older_than_days: int | None = Field(default=None, ge=1)
    delete_older_than_latest_downloads: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_older_than_limit(self):
        if self.delete_older_than == "all":
            if self.delete_older_than_days is not None or self.delete_older_than_latest_downloads is not None:
                raise ValueError("Delete all does not accept an age limit")
        elif self.delete_older_than == "days":
            if self.delete_older_than_days is None or self.delete_older_than_latest_downloads is not None:
                raise ValueError("Delete older than days requires a number of days")
        else:
            if self.delete_older_than_latest_downloads is None or self.delete_older_than_days is not None:
                raise ValueError("Delete older than latest downloads requires a number of downloads")
        return self


class CollectionDeleteDownloadsAPIRequest(_CollectionDownloadMaintenanceAPIRequest):
    """Select downloads to delete by Local Media Profile."""


class CollectionRedownloadEpisodesAPIRequest(_CollectionDownloadMaintenanceAPIRequest):
    """Select downloads to delete and re-download by Local Media Profile."""


# ---------- Lenient output (read) ----------
class _CollectionAPIBaseOut(SourcedResponse, CustomMetadataResponseBase):
    """Fields for responses: no validators, no constraints."""

    model_config = response_model_config(nested_source="collection")

    custom_metadata: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices(
            "custom_metadata",
            "meta_items",
            AliasPath("collection", "meta_items"),
        ),
    )
    id: int
    uuid: str
    slug: str
    membership_level: Optional[Union[DwMembershipLevel, str]] = None
    type: Union[CollectionType, str]
    episode_identifier: Union[EpisodeIdentifier, str]
    author_slug: str
    title: str
    description: Optional[str] = None
    sharing_url: str
    site: Optional[SiteAPIRead] = None
    """The website the collection is on; None until the background migration finds it for an older collection."""
    author_name: str
    author_headshot_path: Optional[str] = None
    background_image_path: Optional[str] = None
    logo_image_path: Optional[str] = None
    thumbnail_landscape_path: Optional[str] = None
    thumbnail_portrait_path: Optional[str] = None
    thumbnail_square_path: Optional[str] = None
    ytdlp_options: str = ""
    cookies_mode: CookiesMode = CookiesMode.AUTOMATIC
    cookies_needed_until: Optional[datetime] = None
    check_frequency: CheckFrequency = CheckFrequency.DEFAULT
    check_cron: Optional[str] = None


class CollectionAPIRead(_CollectionAPIBaseOut):
    """Response body for a collection."""
    created_at: datetime
    updated_at: datetime
    added_by: Optional[str] = None
    """Who added it, with user accounts on."""


class CollectionAPIReadView(CollectionAPIRead):
    """Response body for a collection view."""

    episode_count: int = Field(default=0)
    years: str = Field(default="")


class CollectionSyncLogEntryAPIRead(ResponseBase):
    """One scan that looked at the Collection."""

    id: int
    kind: Literal["full_scan", "quick_check"]
    status: str
    ran_at: Optional[datetime]
    episodes_found: Optional[int]


class CollectionSyncLogAPIRead(ResponseBase):
    items: list[CollectionSyncLogEntryAPIRead]
    total: int
