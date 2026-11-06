"""How long VODLoft looks a published item up again, so changes made after publication reach it.

Each Site follows its own schedule from ``siteSchedules`` in config.yml, then the one
the sources package knows for it, then the system schedule; or none when it is off. A schedule
is a list of offsets after publication; once the last one has passed and the item
was looked up, its metadata is final. The metadata refresh sweep follows every
item: those of a Source with ``Feature.METADATA_REFRESH`` are looked up in batches
through the Source, and those of a Source with ``Feature.EPISODE_LOOKUPS`` one by one.
A Source that lists its episodes (``Feature.EPISODE_LISTS``) and has no metadata
refresh keeps them up to date with its daily catalogue refresh instead: The Daily
Wire's lookup must never touch those, because its "not found" would mark them as
having no usable media.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.db.datetime_types import utc_datetime
from config import get_settings
from config.settings.submodels import SITE_REFRESH_OFF, SiteSchedule, parse_metadata_refresh_intervals
from sources import Feature, UnknownSourceError, get_source, site_refresh_intervals


def own_site_schedule(site_key: Optional[str]) -> SiteSchedule:
    """What config.yml sets for the Site; a setting it leaves out is None."""
    return get_settings().site_schedules.get(site_key, SiteSchedule()) if site_key else SiteSchedule()


def default_metadata_refresh(site_key: Optional[str]) -> str:
    """The schedule a Site follows when config.yml sets none: the one the sources package knows for it, or the system schedule."""
    known = site_refresh_intervals(site_key) if site_key else None
    return known or get_settings().new_episode_schedule.metadata_refresh_intervals


def site_metadata_refresh(site_key: Optional[str]) -> str:
    """The Site's schedule, such as ``30m,2h,24h``, or ``off``."""
    return own_site_schedule(site_key).metadata_refresh or default_metadata_refresh(site_key)


def site_refresh_offsets(site_key: Optional[str]) -> tuple[int, ...]:
    """The Site's schedule in seconds after publication; none when it is off. An item without a Site follows the system schedule."""
    schedule = site_metadata_refresh(site_key)
    return () if schedule == SITE_REFRESH_OFF else parse_metadata_refresh_intervals(schedule)


def refresh_deadline(publication_time: Optional[datetime], offsets: tuple[int, ...]) -> Optional[datetime]:
    if publication_time is None or not offsets:
        return None
    return utc_datetime(publication_time) + timedelta(seconds=offsets[-1])


def refresh_watch_expired(
    publication_time: Optional[datetime], offsets: tuple[int, ...], *, now: Optional[datetime] = None,
) -> bool:
    """Whether the last refresh of the schedule is due; always so without a publication time or a schedule."""
    deadline = refresh_deadline(publication_time, offsets)
    if deadline is None:
        return True
    return utc_datetime(now or datetime.now(timezone.utc)) >= deadline


def sweeps_metadata(source_key: str) -> bool:
    """Whether the metadata refresh sweep looks this Source's items up again in batches, through the Source."""
    try:
        return get_source(source_key).has(Feature.METADATA_REFRESH)
    except UnknownSourceError:
        return False


def refreshes_one_by_one(source_key: str) -> bool:
    """Whether VODLoft looks this Source's episodes up again one by one, as for The Daily Wire."""
    try:
        source = get_source(source_key)
    except UnknownSourceError:
        return False
    return source.has(Feature.EPISODE_LOOKUPS)


def refreshes_metadata(source_key: str) -> bool:
    """Whether VODLoft looks this Source's items up again after they are published."""
    return sweeps_metadata(source_key) or refreshes_one_by_one(source_key)


def new_item_metadata_is_final(
    *, source_key: str, site_key: Optional[str], published_at: Optional[datetime],
) -> bool:
    """Whether a new item of a swept Source is done from the start, such as an old video added from a back catalogue."""
    if not sweeps_metadata(source_key):
        return True
    return refresh_watch_expired(published_at, site_refresh_offsets(site_key))
