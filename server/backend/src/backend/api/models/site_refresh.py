from __future__ import annotations

from typing import Optional

from pydantic import Field, ValidationInfo, field_validator

from backend.api.models.base import RequestBase, ResponseBase, response_model_config
from backend.types.site_types import PENDING_MINIMUM_MINUTES, SiteRefreshMode
from config.settings.submodels import normalize_metadata_refresh_intervals


class SiteRefreshAPIRead(ResponseBase):
    """A Site's metadata refresh schedule, read from a ``SiteRefresh`` envelope."""

    model_config = response_model_config(nested_source="site")

    key: str
    name: str
    domains: list[str]
    refresh_mode: SiteRefreshMode
    refresh_intervals: Optional[str] = None
    pending_checks: bool
    pending_upcoming_minutes: int
    pending_starting_minutes: int
    pending_live_minutes: int
    # Whether a Source the Site's collections and videos come through looks items up again.
    refreshes: bool
    # Whether a Source the Site's collections come through can add upcoming and live videos.
    checks_pending: bool
    # Whether a Source the Site's collections come through follows upcoming and live episodes.
    follows_pending: bool


class SiteRefreshAPIUpdate(RequestBase):
    refresh_mode: SiteRefreshMode
    # Left out, the Site keeps its choice.
    pending_checks: Optional[bool] = None
    # Left out, the Site keeps how often its upcoming and live episodes are looked up.
    pending_upcoming_minutes: Optional[int] = Field(default=None, ge=PENDING_MINIMUM_MINUTES, le=24 * 60)
    pending_starting_minutes: Optional[int] = Field(default=None, ge=PENDING_MINIMUM_MINUTES, le=60)
    pending_live_minutes: Optional[int] = Field(default=None, ge=PENDING_MINIMUM_MINUTES, le=60)
    # Kept while the Site follows another schedule, so it is back when the Site gets its own again.
    refresh_intervals: Optional[str] = Field(default=None, validate_default=True)

    @field_validator("refresh_intervals")
    @classmethod
    def _validate_refresh_intervals(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        if value is not None and value.strip():
            return normalize_metadata_refresh_intervals(value)
        if info.data.get("refresh_mode") == SiteRefreshMode.OWN.value:
            raise ValueError("A Site with its own schedule needs refresh intervals")
        return None
