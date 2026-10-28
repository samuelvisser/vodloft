"""The daily catalogue refresh, for shows whose Source has ``Feature.CATALOGUE_REFRESH``.

It runs after the daily re-scan and brings the episodes VODLoft already has up
to date: renamed videos, new thumbnails, and videos the Source no longer has.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Show
from config.network import is_no_internet_error
from sources import Feature, get_source
from ...helpers.listed_shows import refresh_listed_show

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefreshResult:
    shows: int
    updated: int
    removed: int
    returned: int
    failed: tuple[str, ...]

    def summary(self) -> str:
        text = f"Refreshed {self.shows} {'show' if self.shows == 1 else 'shows'}: {self.updated} episodes updated"
        if self.removed:
            text += f", {self.removed} no longer at the Source"
        if self.returned:
            text += f", {self.returned} back at the Source"
        return f"{text}; could not refresh {', '.join(self.failed)}" if self.failed else text

    def as_data(self) -> dict:
        return {
            "shows": self.shows, "updated": self.updated, "removed": self.removed,
            "returned": self.returned, "failed": list(self.failed),
        }


def run_catalogue_refresh(s: Session, *, show_id: int | None = None) -> RefreshResult:
    """Refresh one show, or every show whose Source can refresh its items."""
    query = select(Show).order_by(Show.id)
    if show_id is not None:
        query = query.where(Show.id == show_id)
    shows = [
        (show.id, show.title, get_source(show.source_key)) for show in s.scalars(query).all()
        if get_source(show.source_key).has(Feature.CATALOGUE_REFRESH)
        and get_source(show.source_key).has(Feature.EPISODE_LISTS)
    ]
    updated = removed = returned = 0
    failed: list[str] = []
    for show_id_, title, source in shows:
        try:
            counts = refresh_listed_show(s, show_id=show_id_, source=source)
        except Exception as exc:
            s.rollback()
            if is_no_internet_error(exc):
                raise
            logger.warning("Could not refresh %s: %s", title, exc)
            failed.append(title)
            continue
        updated, removed, returned = updated + counts.updated, removed + counts.removed, returned + counts.returned
    return RefreshResult(shows=len(shows), updated=updated, removed=removed, returned=returned, failed=tuple(failed))
