from __future__ import annotations

from datetime import date, datetime

from pydantic import Field, model_validator

from backend.api.models.base import ResponseBase, RequestBase, response_model_config
from backend.api.models.season import SeasonAPIRequestDetached, SeasonAPIRead
from backend.types.download_profile_types import EpisodeTagKey


# ---------- Strict input (create/update) ----------
class DownloadProfileAPIBaseIn(RequestBase):
    """Fields for requests: validate here (constraints allowed).

    The season fields only apply to a show identified by season, the other
    filters apply to every show.
    """

    enable_profile: bool
    ep_id_type_list: list[EpisodeTagKey]

    download_with_countdown: bool
    redownload_final: bool
    download_days_in_past: int = Field(ge=0)
    download_episode_count: int = Field(ge=0)
    download_starting_from: date | None
    delete_older_episodes: bool

    seasons: list[SeasonAPIRequestDetached]
    include_upcoming_seasons: bool

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
    """Request body for creating a download profile while bundling it with a show and media profile."""
    pass


class DownloadProfileAPICreate(DownloadProfileAPIBaseIn):
    """Request body for creating a download profile."""

    show_id: int
    local_media_profile_id: int


class DownloadProfileAPIUpdate(DownloadProfileAPIBaseIn):
    """Request body for updating a download profile."""

    local_media_profile_id: int


# ---------- Lenient output (read) ----------
class DownloadProfileAPIBaseOut(ResponseBase):
    model_config = response_model_config(nested_source="profile")

    id: int
    show_id: int
    local_media_profile_id: int
    enable_profile: bool
    ep_id_type_list: list[EpisodeTagKey]

    download_with_countdown: bool
    redownload_final: bool
    download_days_in_past: int
    download_episode_count: int
    download_starting_from: date | None
    delete_older_episodes: bool

    seasons: list[SeasonAPIRead]
    include_upcoming_seasons: bool


class DownloadProfileAPIRead(DownloadProfileAPIBaseOut):
    """Response body for a download profile."""

    created_at: datetime
    updated_at: datetime
