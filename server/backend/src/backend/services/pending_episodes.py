"""Which Sources and Sites VODLoft follows upcoming and live episodes of, and how.

A Site follows the system setting for each of these, its preset, or its own under ``siteSettings`` in config.yml.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.services.site_settings import site_setting
from config.settings.site_settings import SiteSetting
from sources import Feature, Source, UnknownSourceError, get_source


@dataclass(frozen=True)
class PendingMinutes:
    """How often upcoming and live episodes are looked up."""

    upcoming: int
    starting: int
    live: int


def site_pending_minutes(site_key: Optional[str]) -> PendingMinutes:
    """How often the Site's upcoming and live episodes are looked up."""
    minutes = site_setting(site_key, SiteSetting.LOOKUP_MINUTES)
    return PendingMinutes(minutes.upcoming, minutes.starting, minutes.live)


def site_follows_pending(site_key: Optional[str]) -> bool:
    """Whether the Site's upcoming and live videos are added and followed until they are published."""
    return site_setting(site_key, SiteSetting.UPCOMING_AND_LIVE)


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
