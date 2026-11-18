"""The extra index: VODLoft's own number for every extra of a collection.

An extra is an episode of an Extras season, or an episode of a type other than ep, such as an auxiliary
episode, a trailer, an episode extra or a YouTube Short. The collection's extras share one count, in the
order of their episode index, so Media Servers can list them all as specials without two sharing a number.
An extra keeps its number, so its files keep their names: a new extra takes the next number, and an
episode that stops being an extra gives its number up.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.db.models import Season
from backend.db.models.media_item import Episode
from backend.types.season_types import SeasonType
from sources import MAIN_TAG


def is_extra(season_type: Optional[str], episode_identifier: Optional[str]) -> bool:
    """Whether an episode is an extra, as the Media Server output templates tell."""
    return season_type == SeasonType.EXTRA.value or (episode_identifier or "").partition(".")[0] != MAIN_TAG


def number_extras(session: Session, collection_id: int) -> None:
    """Give the collection's new extras their numbers, in the caller's write transaction."""
    rows = session.execute(
        select(Episode.id, Episode.extra_index, Episode.episode_identifier, Season.season_type)
        .join(Season, Season.id == Episode.season_id)
        .where(Episode.collection_id == collection_id)
        .order_by(Episode.index.asc(), Episode.id.asc())
    ).all()
    highest = max((row.extra_index or 0 for row in rows), default=0)
    changes: dict[int, Optional[int]] = {}
    for row in rows:
        extra = is_extra(row.season_type, row.episode_identifier)
        if extra and row.extra_index is None:
            highest += 1
            changes[row.id] = highest
        elif not extra and row.extra_index is not None:
            changes[row.id] = None
    for episode_id, number in changes.items():
        session.execute(update(Episode).where(Episode.id == episode_id).values(extra_index=number))
