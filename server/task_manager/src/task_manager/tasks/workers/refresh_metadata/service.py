"""The metadata refresh sweep, for items of Sources with ``Feature.METADATA_REFRESH``.

A creator can change a video's title, description or thumbnail after publishing
it. While an episode or single video's metadata is not final, the sweep looks it
up again each time one of its Site's intervals passes, counted from publication.
After the last interval it is final.

The sweep keeps no schedule per item. It remembers when it last ran, and an item
is due when one of its intervals passed since then. After a restart nothing is
remembered, so the first sweep looks every unfinished item up once. A lookup
that fails is tried again a couple of times within the sweep, and otherwise waits
for the item's next interval.

Items are looked up per Source in one go, so the yt-dlp Source can ask the
YouTube API for 50 videos at a time.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.datetime_types import utc_datetime
from backend.db.models import Collection, Episode, Site, Video
from backend.services.metadata_refresh import refresh_watch_expired, site_refresh_offsets, sweeps_metadata
from backend.types.episode_types import EpisodePublishStatus
from backend.utils.episode_publication_timing import best_effort_published_date
from sources import ItemRef, VideoDetails, all_sources, get_source
from ...helpers.refreshed_metadata import apply_refreshed_details

logger = logging.getLogger(__name__)

_ATTEMPTS = 3
_last_sweep: Optional[datetime] = None


@dataclass
class SiteCounts:
    checked: int = 0
    updated: int = 0
    removed: int = 0
    failed: int = 0
    finished: int = 0


@dataclass(frozen=True)
class SweepResult:
    sites: dict[str, SiteCounts] = field(default_factory=dict)

    def summary(self) -> str:
        checked = {name: counts for name, counts in self.sites.items() if counts.checked}
        if not checked:
            return "No metadata refresh is due"
        parts = []
        for name, counts in sorted(checked.items()):
            text = f"{name}: looked up {counts.checked}, {counts.updated} changed"
            if counts.removed:
                text += f", {counts.removed} no longer at the Source"
            if counts.failed:
                text += f", {counts.failed} could not be looked up"
            parts.append(text)
        return "; ".join(parts)

    def as_data(self) -> dict:
        return {name: vars(counts) for name, counts in self.sites.items()}


@dataclass(frozen=True)
class _Watched:
    model: type[Episode] | type[Video]
    id: int
    source_key: str
    site_name: str
    ref: ItemRef
    published: Optional[datetime]
    offsets: tuple[int, ...]

    def due(self, since: Optional[datetime], now: datetime) -> bool:
        """Whether one of the item's intervals passed since the last sweep; all are due after a restart."""
        if since is None:
            return True
        published = utc_datetime(self.published)
        return any(since < published + timedelta(seconds=offset) <= now for offset in self.offsets)


def _site_name(site: Optional[Site]) -> str:
    return site.name if site is not None else "Other sites"


def _watched(s: Session, source_keys: list[str]) -> Iterator[_Watched]:
    episodes = s.scalars(
        select(Episode).join(Collection, Collection.id == Episode.collection_id).where(
            Episode.metadata_is_final.is_(False),
            Episode.publish_status == EpisodePublishStatus.PUBLISHED_FINAL.value,
            Episode.source_key.in_(source_keys),
        ).order_by(Episode.id)
    )
    for episode in episodes:
        site = episode.collection.site
        yield _Watched(
            Episode, episode.id, episode.source_key, _site_name(site), ItemRef(episode.source_slug, episode.sharing_url),
            best_effort_published_date(episode), site_refresh_offsets(site),
        )
    videos = s.scalars(
        select(Video).where(Video.metadata_is_final.is_(False), Video.source_key.in_(source_keys)).order_by(Video.id)
    )
    for video in videos:
        yield _Watched(
            Video, video.id, video.source_key, _site_name(video.site), ItemRef(video.slug, video.sharing_url),
            video.published_at, site_refresh_offsets(video.site),
        )


@dataclass
class _Answers:
    details: dict[str, VideoDetails] = field(default_factory=dict)
    removed: set[str] = field(default_factory=set)


def _look_up(source_key: str, refs: list[ItemRef]) -> _Answers:
    """What the Source says about these items, asking again a couple of times for the ones it could not answer."""
    source = get_source(source_key)
    answers = _Answers()
    pending = list({ref.slug: ref for ref in refs}.values())
    for attempt in range(_ATTEMPTS):
        try:
            refresh = source.refresh_metadata(pending)
        except Exception:
            logger.warning("%s could not refresh %d items (attempt %d)", source.name, len(pending), attempt + 1, exc_info=True)
        else:
            answers.details.update(refresh.details)
            answers.removed.update(refresh.removed)
        pending = [ref for ref in pending if ref.slug not in answers.details and ref.slug not in answers.removed]
        if not pending:
            break
    return answers


def run_metadata_refresh(s: Session, *, now: Optional[datetime] = None) -> SweepResult:
    global _last_sweep
    now = utc_datetime(now or datetime.now(timezone.utc))
    since = _last_sweep
    source_keys = [source.id for source in all_sources() if sweeps_metadata(source.id)]
    due: list[_Watched] = []
    finished: list[_Watched] = []
    for item in _watched(s, source_keys):
        if not item.offsets or item.published is None:
            # The Site's refresh is off, or there is no publication to count from.
            finished.append(item)
        elif item.due(since, now):
            due.append(item)
        elif refresh_watch_expired(item.published, item.offsets, now=now):
            finished.append(item)

    # No transaction stays open while the Sources look items up.
    s.rollback()
    answers: dict[str, _Answers] = {}
    for source_key in dict.fromkeys(item.source_key for item in due):
        answers[source_key] = _look_up(source_key, [item.ref for item in due if item.source_key == source_key])

    sites: dict[str, SiteCounts] = {}
    for item in due:
        counts = sites.setdefault(item.site_name, SiteCounts())
        counts.checked += 1
        row = s.get(item.model, item.id)
        if row is None or row.metadata_is_final:
            continue
        answer = answers[item.source_key]
        if item.ref.slug in answer.removed:
            if not row.removed_from_source:
                row.removed_from_source = True
                counts.removed += 1
        elif (details := answer.details.get(item.ref.slug)) is not None:
            row.removed_from_source = False
            counts.updated += apply_refreshed_details(row, details)
        else:
            counts.failed += 1
        if refresh_watch_expired(item.published, item.offsets, now=now):
            row.metadata_is_final = True
            counts.finished += 1
    for item in finished:
        row = s.get(item.model, item.id)
        if row is not None:
            row.metadata_is_final = True
            sites.setdefault(item.site_name, SiteCounts()).finished += 1
    s.commit()
    _last_sweep = now
    return SweepResult(sites)
