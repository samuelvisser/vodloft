from __future__ import annotations

from typing import Optional

from backend.api.models.base import ResponseBase, response_model_config


class SiteRefreshAPIRead(ResponseBase):
    """A Site the Automation settings schedule, read from a ``SiteRefresh`` envelope. Its own
    scheduling is part of the settings, under ``siteSchedules``."""

    model_config = response_model_config(nested_source="site")

    key: str
    name: str
    domains: list[str]
    # Whether a Source the Site's collections and videos come through looks items up again.
    refreshes: bool
    # Whether a Source the Site's collections come through follows upcoming and live episodes.
    follows_pending: bool
    # The schedule the Site follows unless the settings give it one; None follows the system schedule.
    default_refresh_intervals: Optional[str] = None
