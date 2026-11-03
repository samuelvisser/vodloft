"""How often VODLoft looks for new episodes of a Collection, as chosen on its edit page."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Collection, Episode
from backend.types.collection_types import CheckFrequency

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


def quick_check_minutes(collection: Collection, minutes: int) -> int:
    """The minutes between quick checks of this Collection, given what its Source would use."""
    if collection.check_frequency == CheckFrequency.LESS_OFTEN:
        return max(minutes, LESS_OFTEN_MINUTES)
    return minutes


_SUGGEST_AFTER = timedelta(days=21)


def check_suggestion(session: Session, collection: Collection) -> Optional[str]:
    """A hint on the edit page, once VODLoft has seen the Collection post for about three weeks."""
    rows = session.scalars(
        select(Episode.published_date)
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
