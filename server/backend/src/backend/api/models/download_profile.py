from __future__ import annotations

from datetime import date, datetime

from pydantic import Field, field_validator, model_validator

from backend.api.models.base import ResponseBase, RequestBase, response_model_config
from backend.api.models.collection_example import ExampleCollectionAPIIn
from backend.services.regex_check import MAX_PATTERN_LENGTH, PatternError, compile_pattern, split_inline_ignore_case
from backend.types.download_profile_types import (
    DATE_FIELDS,
    DurationOperator,
    EpisodeFilterAction,
    EpisodeFilterField,
    EpisodeTagKey,
    AutoSubtitles,
    DEFAULT_SPONSORBLOCK_SEGMENTS,
    SponsorBlockAction,
    SponsorBlockCategory,
    DEFAULT_UPGRADE_IMPROVEMENTS,
    UpgradeImprovement,
    UpgradeRepeat,
)


class DownloadProfileFilterAPIIn(RequestBase):
    """One line of Which episodes."""

    action: EpisodeFilterAction
    field: EpisodeFilterField
    pattern: str | None = Field(default=None, max_length=MAX_PATTERN_LENGTH)
    """A title or description line's regular expression; a leading (?i) ignores case."""
    duration_operator: DurationOperator | None = None
    duration_seconds: int | None = Field(default=None, ge=1)
    episode_types: list[EpisodeTagKey] | None = None
    season_slugs: list[str] | None = None
    include_upcoming: bool = False
    days: int | None = Field(default=None, ge=1)
    count: int | None = Field(default=None, ge=1)
    starting_from: date | None = None

    @model_validator(mode="after")
    def _validate_filter(self):
        if self.field in DATE_FIELDS:
            if self.action == EpisodeFilterAction.SKIP:
                raise ValueError("A date line can only download or keep episodes")
            if self.field == EpisodeFilterField.DOWNLOADED:
                if self.days is None or self.count is not None or self.starting_from is not None:
                    raise ValueError("Choose a number of days")
            elif sum(value is not None for value in (self.days, self.count, self.starting_from)) != 1:
                raise ValueError("Choose a number of days, a number of episodes or a date")
            return self
        if self.field == EpisodeFilterField.TYPES:
            if not self.episode_types:
                raise ValueError("Choose at least one episode type")
            return self
        if self.field == EpisodeFilterField.SEASONS:
            if not self.season_slugs and not self.include_upcoming:
                raise ValueError("Choose at least one season, or upcoming seasons")
            return self
        if self.field == EpisodeFilterField.DURATION:
            if self.duration_operator is None or self.duration_seconds is None:
                raise ValueError("A duration filter needs shorter or longer than, and a duration")
            return self
        try:
            compile_pattern(*split_inline_ignore_case(self.pattern or "", False))
        except PatternError as exc:
            raise ValueError(str(exc)) from None
        return self


def _one_line_per_date(filters: list[DownloadProfileFilterAPIIn]) -> list[DownloadProfileFilterAPIIn]:
    for date_field in DATE_FIELDS:
        if sum(item.field == date_field for item in filters) > 1:
            raise ValueError(f"Use one {date_field} line at most")
    return filters


class DownloadProfileFilterAPIRead(ResponseBase):
    id: int
    action: EpisodeFilterAction
    field: EpisodeFilterField
    pattern: str | None
    duration_operator: DurationOperator | None
    duration_seconds: int | None
    episode_types: list[str] | None = None
    season_slugs: list[str] | None = None
    include_upcoming: bool
    days: int | None
    count: int | None
    starting_from: date | None


# ---------- Strict input (create/update) ----------
class DownloadProfileAPIBaseIn(RequestBase):
    """Fields for requests: validate here (constraints allowed)."""

    enable_profile: bool

    download_with_countdown: bool
    redownload_final: bool
    delete_older_episodes: bool
    auto_subtitles: AutoSubtitles = AutoSubtitles.FALLBACK
    sponsorblock_enabled: bool = True
    sponsorblock_segments: dict[SponsorBlockCategory, SponsorBlockAction] = Field(
        default_factory=lambda: dict(DEFAULT_SPONSORBLOCK_SEGMENTS),
    )
    upgrade_check: bool = True
    upgrade_after_days: int = Field(default=7, ge=1, le=365)
    upgrade_repeat: UpgradeRepeat = UpgradeRepeat.ONCE
    upgrade_improvements: list[UpgradeImprovement] = Field(
        default_factory=lambda: list(DEFAULT_UPGRADE_IMPROVEMENTS), max_length=len(UpgradeImprovement),
    )
    upgrade_length_minutes: int = Field(default=5, ge=1, le=600)

    filters: list[DownloadProfileFilterAPIIn] = Field(default_factory=list, max_length=50)

    @field_validator("sponsorblock_segments")
    @classmethod
    def _validate_sponsorblock_segments(cls, value: dict) -> dict:
        if set(value) != {category.value for category in SponsorBlockCategory}:
            raise ValueError("Choose Keep, Chapter or Cut out for every SponsorBlock segment type")
        return value

    @field_validator("upgrade_improvements")
    @classmethod
    def _unique_improvements(cls, value: list) -> list:
        return list(dict.fromkeys(value))

    _one_line_per_date = field_validator("filters")(classmethod(lambda cls, value: _one_line_per_date(value)))


class DownloadProfileAPICreateBundle(DownloadProfileAPIBaseIn):
    """Request body for creating a download profile while bundling it with a collection and media profile."""
    pass


class DownloadProfileAPICreate(DownloadProfileAPIBaseIn):
    """Request body for creating a download profile."""

    collection_id: int
    local_media_profile_id: int


class DownloadProfileAPIUpdate(DownloadProfileAPIBaseIn):
    """Request body for updating a download profile."""

    local_media_profile_id: int


# ---------- Lenient output (read) ----------
class DownloadProfileAPIBaseOut(ResponseBase):
    model_config = response_model_config(nested_source="profile")

    id: int
    collection_id: int
    local_media_profile_id: int
    enable_profile: bool

    download_with_countdown: bool
    redownload_final: bool
    delete_older_episodes: bool
    auto_subtitles: AutoSubtitles
    sponsorblock_enabled: bool
    sponsorblock_segments: dict[str, SponsorBlockAction]
    upgrade_check: bool
    upgrade_after_days: int
    upgrade_repeat: UpgradeRepeat
    upgrade_improvements: list[UpgradeImprovement]
    upgrade_length_minutes: int

    filters: list[DownloadProfileFilterAPIRead]


class DownloadProfileAPIRead(DownloadProfileAPIBaseOut):
    """Response body for a download profile."""

    created_at: datetime
    updated_at: datetime


# ---------- Which episodes ----------
class WhichEpisodesAPIRequest(RequestBase):
    """The Which episodes lines of a profile form, saved or not, to count against a Collection.

    A Collection that is not saved yet is counted on its newest episodes, given as ``example_collection``.
    """

    collection_id: int | None = None
    example_collection: ExampleCollectionAPIIn | None = None
    download_with_countdown: bool
    filters: list[DownloadProfileFilterAPIIn] = Field(default_factory=list, max_length=50)
    include_episodes: bool = False
    # The episode list is read a page at a time, newest first, as the form scrolls through it.
    episodes_offset: int = Field(default=0, ge=0)
    episodes_limit: int = Field(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def _one_collection(self) -> "WhichEpisodesAPIRequest":
        if (self.collection_id is None) == (self.example_collection is None):
            raise ValueError("Give either collectionId or exampleCollection")
        return self


class WhichEpisodesEpisodeAPIRead(ResponseBase):
    id: int
    slug: str
    title: str
    published_at: datetime | None
    left_out_by: str | None
    """None when the episode will be downloaded; otherwise unavailable, or filter:<index>."""


class WhichEpisodesAPIRead(ResponseBase):
    total: int
    unavailable: int
    filters: list[int]
    """How many episodes each filter leaves out, in the order they were sent; 0 for Keep."""
    downloaded: int
    episodes: list[WhichEpisodesEpisodeAPIRead] | None = None
    """One page of the Collection's indexed episodes, from episodes_offset; None unless include_episodes."""


class SkippedByFilterAPIRead(ResponseBase):
    """An episode a Download Profile would download if one of its filters did not leave it out."""

    episode_id: int
    download_profile_id: int
    local_media_profile_id: int
    filter: DownloadProfileFilterAPIRead


class AutoSubtitlesUseAPIRead(ResponseBase):
    """A YouTube Download Profile that uses a Local Media Profile, and its auto-generated subtitle choice."""

    download_profile_id: int
    collection_id: int
    collection_title: str
    auto_subtitles: AutoSubtitles
