from __future__ import annotations

from enum import StrEnum


class SiteRefreshMode(StrEnum):
    """Which schedule a Site's items follow while VODLoft looks their metadata up again."""

    OFF = "off"
    SYSTEM = "system"
    """The system schedule, ``new_episode_schedule.metadata_refresh_intervals``."""
    OWN = "own"
    """The Site's own ``refresh_intervals``."""
