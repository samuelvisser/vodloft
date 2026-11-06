from __future__ import annotations

from enum import StrEnum


class SiteRefreshMode(StrEnum):
    """Which schedule a Site's items follow while VODLoft looks their metadata up again."""

    OFF = "off"
    SYSTEM = "system"
    """The system schedule, ``new_episode_schedule.metadata_refresh_intervals``."""
    OWN = "own"
    """The Site's own ``refresh_intervals``."""


PENDING_UPCOMING_MINUTES = 60
"""How often a Site's upcoming episodes are looked up, unless the Site says otherwise."""
PENDING_STARTING_MINUTES = 2
"""How often from 15 minutes before an episode's start until an hour after it."""
PENDING_LIVE_MINUTES = 5
"""How often while an episode is live, or the site is still finishing it."""
PENDING_MINIMUM_MINUTES = 2
"""The pending check sweep runs every two minutes, so no interval is shorter."""
