"""Quick checks for new videos, for shows whose Source has ``Feature.QUICK_CHECK``.

A quick check asks the Source for the show's newest items and looks up only the
ones VODLoft does not have yet, which is much cheaper than listing the whole
show. The Source says how often each show can be checked; the daily full
re-scan catches anything a quick check misses.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Episode, Show
from config.network import is_no_internet_error
from sources import Feature, Source, get_source
from ...helpers.listed_shows import add_listed_episodes, known_episode_slugs
from .service import _index_listed_show, _queue_show_indexed

logger = logging.getLogger(__name__)

# The cron that wakes the quick check does not fire to the second.
_SLACK = timedelta(minutes=1)
_last_checked: dict[int, datetime] = {}


@dataclass(frozen=True)
class QuickCheckResult:
    checked: int
    found: int
    failed: tuple[str, ...]

    def summary(self) -> str:
        if not self.checked:
            return "No show is due for a quick check"
        shows = "show" if self.checked == 1 else "shows"
        videos = "video" if self.found == 1 else "videos"
        text = f"Checked {self.checked} {shows}: {self.found} new {videos}"
        return f"{text}; could not check {', '.join(self.failed)}" if self.failed else text


def _due_shows(s: Session, now: datetime) -> list[tuple[Show, Source, int]]:
    """The shows whose quick check is due, with their Source and episode count."""
    counts = dict(s.execute(select(Episode.show_id, func.count()).group_by(Episode.show_id)).all())
    by_source: dict[str, list[Show]] = {}
    for show in s.scalars(select(Show).order_by(Show.id)).all():
        if get_source(show.source_key).has(Feature.QUICK_CHECK):
            by_source.setdefault(show.source_key, []).append(show)
    due = []
    for source_key, shows in by_source.items():
        source = get_source(source_key)
        minutes = source.quick_check_minutes([(show.sharing_url, counts.get(show.id, 0)) for show in shows])
        for show in shows:
            last = _last_checked.get(show.id)
            if last is None or now - last >= timedelta(minutes=minutes) - _SLACK:
                due.append((show, source, counts.get(show.id, 0)))
    return due


def _check_show(s: Session, *, show: Show, source: Source) -> int:
    show_id, url = show.id, show.sharing_url
    known = known_episode_slugs(s, show)
    # No transaction stays open while the Source looks videos up.
    s.rollback()
    new = [item for item in source.latest_items(url) if item.slug not in known]
    if not new:
        return 0
    found = [details for details in source.item_details(new).values() if details is not None]
    added = add_listed_episodes(s, show_id=show_id, found=found)
    if added:
        from backend.services.custom_indexes import request_show_custom_index_reconciliation

        request_show_custom_index_reconciliation(s, show_id)
        _queue_show_indexed(s, show=s.get(Show, show_id), indexed_count=added)
    s.commit()
    return added


def run_quick_check(s: Session, *, now: datetime | None = None) -> QuickCheckResult:
    now = now or datetime.now(timezone.utc)
    due = _due_shows(s, now)
    found, failed = 0, []
    for show, source, count in due:
        _last_checked[show.id] = now
        title = show.title
        try:
            if count == 0:
                # A show that was never indexed gets its full first index, so its numbering follows upload order.
                found += _index_listed_show(s, show=show, source=source, dry_run=False).episodes_found
            else:
                found += _check_show(s, show=show, source=source)
        except Exception as exc:
            s.rollback()
            if is_no_internet_error(exc):
                raise
            logger.warning("Could not check %s for new videos: %s", title, exc)
            failed.append(title)
    return QuickCheckResult(checked=len(due), found=found, failed=tuple(failed))
