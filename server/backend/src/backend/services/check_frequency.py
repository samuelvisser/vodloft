"""How often VODLoft looks for new episodes of a Collection, as chosen on its edit page."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Collection, Episode
from backend.services.link_seasons import lists_own_link, own_feeds
from backend.types.collection_types import CheckFrequency
from sources import QuickCheckCollection

LESS_OFTEN_MINUTES = 6 * 60
"""A Collection checked less often is looked at no more than every six hours."""

# When each Collection was last scanned in full, so "less often" can skip the regular scans in between.
_last_full_scan: dict[int, float] = {}


def joins_regular_checks(collection: Collection) -> bool:
    """False for a Collection on its own schedule: the regular checks leave it alone."""
    return collection.check_frequency != CheckFrequency.OWN


def full_scan_due(collection: Collection, *, now: Optional[float] = None) -> bool:
    """Whether a scan of every Collection should include this one now."""
    if not joins_regular_checks(collection):
        return False
    if collection.check_frequency != CheckFrequency.LESS_OFTEN:
        return True
    last = _last_full_scan.get(collection.id)
    return last is None or (now or time.monotonic()) - last >= LESS_OFTEN_MINUTES * 60 - 60


def full_scan_done(collection_id: int) -> None:
    _last_full_scan[collection_id] = time.monotonic()


LISTS_ONLY_MINUTES = 60
"""A Collection that only holds the seasons of its lists reads every one of them again each check, so it is checked
no more than every hour."""


def quick_check_plan(collection: Collection, episode_count: int) -> QuickCheckCollection:
    """The Collection as its Source needs it to tell what quick-checking it costs and how often it can."""
    lists_only = not lists_own_link(collection)
    least = LESS_OFTEN_MINUTES if collection.check_frequency == CheckFrequency.LESS_OFTEN else 0
    return QuickCheckCollection(
        url=collection.sharing_url or "",
        episode_count=episode_count,
        feeds=own_feeds(collection),
        lists_only=lists_only,
        least_minutes=max(least, LISTS_ONLY_MINUTES if lists_only else 0),
    )


_SUGGEST_AFTER = timedelta(days=21)


def check_suggestion(session: Session, collection: Collection) -> Optional[str]:
    """A hint on the edit page, once VODLoft has seen the Collection post for about three weeks. A video in two
    seasons, such as the channel's and a playlist's, is one post."""
    rows = session.scalars(
        select(Episode.published_date).distinct()
        .where(Episode.collection_id == collection.id, Episode.published_date.is_not(None))
        .order_by(Episode.published_date.desc())
        .limit(30)
    ).all()
    times = sorted((value if value.tzinfo else value.replace(tzinfo=timezone.utc)) for value in rows)
    if len(times) < 4 or datetime.now(timezone.utc) - times[0] < _SUGGEST_AFTER:
        return None
    gap = timedelta(seconds=median((later - earlier).total_seconds() for earlier, later in zip(times, times[1:])))
    if gap >= timedelta(days=5):
        days = round(gap / timedelta(days=1))
        return f"This Collection posts about once every {days} days, so checking less often would be enough."
    if gap <= timedelta(hours=12):
        return "This Collection posts several times a day; the default checks suit it best."
    return None
