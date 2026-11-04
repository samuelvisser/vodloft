"""How long VODLoft looks a published item up again, so changes made after publication reach it.

Each Site follows the system schedule, a schedule of its own, or none. A schedule
is a list of offsets after publication; once the last one has passed and the item
was looked up, its metadata is final. Episodes of The Daily Wire go through their
own refresh worker, which follows the same schedule; items of a Source with
``Feature.METADATA_REFRESH`` go through the metadata refresh sweep.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.datetime_types import utc_datetime
from backend.db.models import Site
from backend.types.site_types import SiteRefreshMode
from config import get_settings
from config.settings.submodels import parse_metadata_refresh_intervals
from sources import Feature, UnknownSourceError, get_source


def system_refresh_offsets() -> tuple[int, ...]:
    return parse_metadata_refresh_intervals(get_settings().new_episode_schedule.metadata_refresh_intervals)


def site_refresh_offsets(site: Optional[Site]) -> tuple[int, ...]:
    """The Site's schedule in seconds after publication; none when it is off. An item without a Site follows the system schedule."""
    if site is None or site.refresh_mode == SiteRefreshMode.SYSTEM.value:
        return system_refresh_offsets()
    if site.refresh_mode == SiteRefreshMode.OFF.value or not site.refresh_intervals:
        return ()
    return parse_metadata_refresh_intervals(site.refresh_intervals)


def site_key_refresh_offsets(s: Session, site_key: Optional[str]) -> tuple[int, ...]:
    return site_refresh_offsets(s.get(Site, site_key) if site_key else None)


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
    """Whether the metadata refresh sweep looks this Source's items up again."""
    try:
        return get_source(source_key).has(Feature.METADATA_REFRESH)
    except UnknownSourceError:
        return False


def new_item_metadata_is_final(
    s: Session, *, source_key: str, site_key: Optional[str], published_at: Optional[datetime],
) -> bool:
    """Whether a new item of a swept Source is done from the start, such as an old video added from a back catalogue."""
    if not sweeps_metadata(source_key):
        return True
    return refresh_watch_expired(published_at, site_key_refresh_offsets(s, site_key))
