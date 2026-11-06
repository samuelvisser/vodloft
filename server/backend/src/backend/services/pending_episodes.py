"""Which Sources and Sites VODLoft follows upcoming and live episodes of, and how.

A Site follows the system setting for each of these, or has its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.db.models import Site
from config import get_settings
from sources import Feature, Source, UnknownSourceError, get_source


@dataclass(frozen=True)
class PendingMinutes:
    """How often upcoming and live episodes are looked up."""

    upcoming: int
    starting: int
    live: int


def system_pending_minutes() -> PendingMinutes:
    schedule = get_settings().new_episode_schedule
    return PendingMinutes(schedule.pending_upcoming_minutes, schedule.pending_starting_minutes, schedule.pending_live_minutes)


def own_pending_minutes(site: Optional[Site]) -> Optional[PendingMinutes]:
    """The Site's own lookup times; None when it follows the system setting."""
    if site is None or site.pending_upcoming_minutes is None:
        return None
    return PendingMinutes(site.pending_upcoming_minutes, site.pending_starting_minutes, site.pending_live_minutes)


def site_pending_minutes(site: Optional[Site]) -> PendingMinutes:
    return own_pending_minutes(site) or system_pending_minutes()


def site_follows_pending(site: Optional[Site]) -> bool:
    """Whether the Site's upcoming and live videos are added and followed until they are published."""
    if site is None or site.pending_checks is None:
        return get_settings().new_episode_schedule.upcoming_and_live
    return site.pending_checks


def checks_pending(source: Source) -> bool:
    """The Source looks a batch of upcoming and live episodes up at once, through ``Source.check_pending``."""
    return source.has(Feature.PENDING_CHECKS)


def monitors_pending(source: Source) -> bool:
    """VODLoft looks the Source's upcoming and live episodes up one by one, as for The Daily Wire."""
    return source.has(Feature.LIVE_EPISODES) and source.has(Feature.EPISODE_LOOKUPS)


def follows_pending(source_key: str) -> bool:
    try:
        source = get_source(source_key)
    except UnknownSourceError:
        return False
    return checks_pending(source) or monitors_pending(source)
