from __future__ import annotations

from datetime import date, datetime

from pydantic import Field, field_validator, model_validator

from backend.api.models.base import ResponseBase, RequestBase, response_model_config
from backend.api.models.season import SeasonAPIRequestDetached, SeasonAPIRead
from backend.services.regex_check import MAX_PATTERN_LENGTH, PatternError, compile_pattern, split_inline_ignore_case
from backend.types.download_profile_types import (
    DurationOperator,
    EpisodeRuleAction,
    EpisodeRuleField,
    EpisodeTagKey,
    AutoSubtitles,
    DEFAULT_SPONSORBLOCK_SEGMENTS,
    RetentionFrom,
    SponsorBlockAction,
    SponsorBlockCategory,
)


class DownloadProfileRuleAPIIn(RequestBase):
    """One of your own lines in Which episodes."""

    action: EpisodeRuleAction
    field: EpisodeRuleField
    pattern: str | None = Field(default=None, max_length=MAX_PATTERN_LENGTH)
    ignore_case: bool = False
    duration_operator: DurationOperator | None = None
    duration_seconds: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_rule(self):
        if self.field == EpisodeRuleField.DURATION:
            if self.duration_operator is None or self.duration_seconds is None:
                raise ValueError("A duration rule needs shorter or longer than, and a duration")
            return self
        self.pattern, self.ignore_case = split_inline_ignore_case(self.pattern or "", self.ignore_case)
        try:
            compile_pattern(self.pattern, self.ignore_case)
        except PatternError as exc:
            raise ValueError(str(exc)) from None
        return self


class DownloadProfileRuleAPIRead(ResponseBase):
    id: int
    action: EpisodeRuleAction
    field: EpisodeRuleField
    pattern: str | None
    ignore_case: bool
    duration_operator: DurationOperator | None
    duration_seconds: int | None


# ---------- Strict input (create/update) ----------
class DownloadProfileAPIBaseIn(RequestBase):
    """Fields for requests: validate here (constraints allowed).

    The season fields only apply to a collection identified by season, the other
    filters apply to every collection.
    """

    enable_profile: bool
    ep_id_type_list: list[EpisodeTagKey]

    download_with_countdown: bool
    redownload_final: bool
    download_days_in_past: int = Field(ge=0)
    download_episode_count: int = Field(ge=0)
    download_starting_from: date | None
    delete_older_episodes: bool
    retention_from: RetentionFrom = RetentionFrom.PUBLISHED
    auto_subtitles: AutoSubtitles = AutoSubtitles.FALLBACK
    sponsorblock_enabled: bool = True
    sponsorblock_segments: dict[SponsorBlockCategory, SponsorBlockAction] = Field(
        default_factory=lambda: dict(DEFAULT_SPONSORBLOCK_SEGMENTS),
    )

    seasons: list[SeasonAPIRequestDetached]
    include_upcoming_seasons: bool
    rules: list[DownloadProfileRuleAPIIn] = Field(default_factory=list, max_length=50)

    @field_validator("sponsorblock_segments")
    @classmethod
    def _validate_sponsorblock_segments(cls, value: dict) -> dict:
        if set(value) != {category.value for category in SponsorBlockCategory}:
            raise ValueError("Choose Keep, Chapter or Cut out for every SponsorBlock segment type")
        return value

    @model_validator(mode="after")
    def _validate_download_limit(self):
        if self.download_days_in_past > 0 and self.download_episode_count > 0:
            raise ValueError("Choose either a date limit or an episode-count limit, not both")
        if self.download_starting_from is not None and (
            self.download_days_in_past > 0 or self.download_episode_count > 0
        ):
            raise ValueError("Download starting from can only be used when Limit by is set to No limits")
        return self


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
    ep_id_type_list: list[EpisodeTagKey]

    download_with_countdown: bool
    redownload_final: bool
    download_days_in_past: int
    download_episode_count: int
    download_starting_from: date | None
    delete_older_episodes: bool
    retention_from: RetentionFrom
    auto_subtitles: AutoSubtitles
    sponsorblock_enabled: bool
    sponsorblock_segments: dict[str, SponsorBlockAction]

    seasons: list[SeasonAPIRead]
    include_upcoming_seasons: bool
    rules: list[DownloadProfileRuleAPIRead]


class DownloadProfileAPIRead(DownloadProfileAPIBaseOut):
    """Response body for a download profile."""

    created_at: datetime
    updated_at: datetime


# ---------- Which episodes ----------
class WhichEpisodesAPIRequest(RequestBase):
    """The Which episodes lines of a profile form, saved or not, to count against a Collection."""

    collection_id: int
    ep_id_type_list: list[EpisodeTagKey]
    download_with_countdown: bool
    download_days_in_past: int = Field(ge=0)
    download_episode_count: int = Field(ge=0)
    download_starting_from: date | None
    season_slugs: list[str] = Field(default_factory=list)
    include_upcoming_seasons: bool
    rules: list[DownloadProfileRuleAPIIn] = Field(default_factory=list, max_length=50)
    include_episodes: bool = False


class WhichEpisodesEpisodeAPIRead(ResponseBase):
    id: int
    slug: str
    title: str
    published_at: datetime | None
    left_out_by: str | None
    """None when the episode will be downloaded; otherwise unavailable, types, seasons, dates or rule:<index>."""


class WhichEpisodesAPIRead(ResponseBase):
    total: int
    unavailable: int
    types: int
    seasons: int
    dates: int
    rules: list[int]
    downloaded: int
    episodes: list[WhichEpisodesEpisodeAPIRead] | None = None


class SkippedByFilterAPIRead(ResponseBase):
    """An episode a Download Profile would download if one of its own rules did not leave it out."""

    episode_id: int
    download_profile_id: int
    local_media_profile_id: int
    rule: DownloadProfileRuleAPIRead


class AutoSubtitlesUseAPIRead(ResponseBase):
    """A YouTube Download Profile that uses a Local Media Profile, and its auto-generated subtitle choice."""

    download_profile_id: int
    collection_id: int
    collection_title: str
    episode_types: list[str]
    """The episode types, only when the Collection has more than one Download Profile on this Local Media Profile."""
    auto_subtitles: AutoSubtitles
