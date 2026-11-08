"""The metadata refresh sweep, which follows every published item while its metadata settles.

A creator can change a video's title, description or thumbnail after publishing
it. While an episode or single video's metadata is not final, the sweep looks it
up again each time one of its Site's intervals passes, counted from publication.
After the last interval it is final.

The sweep keeps no schedule per item. It remembers when it last ran, and an item
is due when one of its intervals passed since then. After a restart nothing is
remembered, so the first sweep looks every unfinished item up once. A lookup
that fails is tried again a couple of times within the sweep, and otherwise waits
for the item's next interval.

Items of a Source with ``Feature.METADATA_REFRESH`` are looked up per Source in
one go, so the yt-dlp Source can ask the YouTube API for 50 videos at a time. The
Daily Wire's episodes are looked up one by one by its own refresh, which also
hands an episode over to the pending checks or the no-usable-media checks when
The Daily Wire says it is live again or gone.

Refresh now, for one episode or a whole collection, looks an episode up the same
way right away.
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
from backend.db.core import run_write_transaction
from backend.db.models import Collection, Episode, Site, Video
from backend.services.media_access import lock_refused
from backend.services.metadata_refresh import (
    refresh_watch_expired,
    refreshes_one_by_one,
    site_refresh_offsets,
    sweeps_metadata,
)
from backend.types.episode_types import EpisodePublishStatus
from backend.utils.episode_publication_timing import best_effort_published_date
from sources import ItemRef, VideoDetails, all_sources, get_source
from ...helpers.refreshed_metadata import apply_refreshed_details, check_upgrades_after_refresh
from ..refresh_episode_metadata.service import refresh_dailywire_episode

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
    one_by_one: bool

    def due(self, since: Optional[datetime], now: datetime) -> bool:
        """Whether one of the item's intervals passed since the last sweep; all are due after a restart."""
        if since is None:
            return True
        published = utc_datetime(self.published)
        return any(since < published + timedelta(seconds=offset) <= now for offset in self.offsets)


def _site_name(site: Optional[Site]) -> str:
    return site.name if site is not None else "Other sites"


def _watched_episode(episode: Episode) -> _Watched:
    site = episode.collection.site
    return _Watched(
        Episode, episode.id, episode.source_key, _site_name(site), ItemRef(episode.source_slug, episode.sharing_url),
        best_effort_published_date(episode), site_refresh_offsets(episode.collection.site_key), refreshes_one_by_one(episode.source_key),
    )


def _watched(s: Session, source_keys: list[str]) -> Iterator[_Watched]:
    episodes = s.scalars(
        select(Episode).join(Collection, Collection.id == Episode.collection_id).where(
            Episode.metadata_is_final.is_(False),
            Episode.publish_status == EpisodePublishStatus.PUBLISHED_FINAL.value,
            Episode.source_key.in_(source_keys),
        ).order_by(Episode.id)
    )
    for episode in episodes:
        yield _watched_episode(episode)
    videos = s.scalars(
        select(Video).where(Video.metadata_is_final.is_(False), Video.source_key.in_(source_keys)).order_by(Video.id)
    )
    for video in videos:
        yield _Watched(
            Video, video.id, video.source_key, _site_name(video.site), ItemRef(video.slug, video.sharing_url),
            video.published_at, site_refresh_offsets(video.site_key), False,
        )


@dataclass
class _Answers:
    details: dict[str, VideoDetails] = field(default_factory=dict)
    removed: set[str] = field(default_factory=set)
    refused: dict[str, str] = field(default_factory=dict)


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
            answers.refused.update(refresh.refused)
        pending = [
            ref for ref in pending
            if ref.slug not in answers.details and ref.slug not in answers.removed and ref.slug not in answers.refused
        ]
        if not pending:
            break
    return answers


def _refresh_one_by_one(s: Session, item: _Watched, counts: SiteCounts) -> bool:
    """Whether the episode is still published, after its Source's own refresh looked it up."""
    for attempt in range(_ATTEMPTS):
        try:
            refreshed = refresh_dailywire_episode(s, item.id)
        except Exception:
            s.rollback()
            logger.warning("Could not refresh episode %s (attempt %d)", item.id, attempt + 1, exc_info=True)
            continue
        if refreshed is None:
            return False
        if refreshed:
            counts.updated += 1
            return True
        # It is live again or has no usable media, and the pending or no-usable-media checks follow it.
        row = s.get(Episode, item.id)
        if row is not None and row.publish_status == EpisodePublishStatus.NO_USABLE_MEDIA.value:
            counts.removed += 1
        return False
    counts.failed += 1
    return True


def _refresh(s: Session, due: list[_Watched], now: datetime) -> dict[str, SiteCounts]:
    # No transaction stays open while the Sources look items up.
    s.rollback()
    batched = [item for item in due if not item.one_by_one]
    answers: dict[str, _Answers] = {}
    for source_key in dict.fromkeys(item.source_key for item in batched):
        answers[source_key] = _look_up(source_key, [item.ref for item in batched if item.source_key == source_key])

    sites: dict[str, SiteCounts] = {}
    for item in due:
        counts = sites.setdefault(item.site_name, SiteCounts())
        counts.checked += 1
        if item.one_by_one and not _refresh_one_by_one(s, item, counts):
            continue
        stored = run_write_transaction(lambda w, item=item: _store(w, item, answers.get(item.source_key), now))
        for name in ("updated", "removed", "failed", "finished"):
            setattr(counts, name, getattr(counts, name) + getattr(stored, name))
    return sites


def _store(w: Session, item: _Watched, answer: _Answers | None, now: datetime) -> SiteCounts:
    """Store what the Source said about one item. Returns what changed, to add to its Site's counts."""
    counts = SiteCounts()
    row = w.get(item.model, item.id)
    if row is None or row.metadata_is_final:
        return counts
    if not item.one_by_one:
        if item.ref.slug in answer.removed:
            if not row.removed_from_source:
                row.removed_from_source = True
                counts.removed += 1
        elif (details := answer.details.get(item.ref.slug)) is not None or item.ref.slug in answer.refused:
            row.removed_from_source = False
            if details is not None:
                counts.updated += apply_refreshed_details(row, details)
                if isinstance(row, Episode):
                    check_upgrades_after_refresh(w, row)
            if (access := answer.refused.get(item.ref.slug)) is not None and row.access_refused_at is None:
                lock_refused(row, access, now=now)
        else:
            counts.failed += 1
    if refresh_watch_expired(item.published, item.offsets, now=now):
        row.metadata_is_final = True
        counts.finished += 1
    return counts


def run_metadata_refresh(s: Session, *, now: Optional[datetime] = None) -> SweepResult:
    global _last_sweep
    now = utc_datetime(now or datetime.now(timezone.utc))
    since = _last_sweep
    source_keys = [source.id for source in all_sources() if sweeps_metadata(source.id) or refreshes_one_by_one(source.id)]
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

    sites = _refresh(s, due, now)

    def finish(w: Session) -> list[str]:
        """The Site of each item whose watch ended."""
        names = []
        for item in finished:
            row = w.get(item.model, item.id)
            if row is not None:
                row.metadata_is_final = True
                names.append(item.site_name)
        return names

    if finished:
        for name in run_write_transaction(finish):
            sites.setdefault(name, SiteCounts()).finished += 1
    _last_sweep = now
    return SweepResult(sites)


def refresh_episode_now(s: Session, episode_id: int, *, now: Optional[datetime] = None) -> SweepResult:
    """Look one published episode up again right away, as Refresh now asks.

    Its metadata is no longer final, so the sweep follows it again for as long as
    its Site's schedule says.
    """
    now = utc_datetime(now or datetime.now(timezone.utc))

    def follow_again(w: Session) -> _Watched | None:
        episode = w.get(Episode, episode_id)
        if episode is None or episode.publish_status != EpisodePublishStatus.PUBLISHED_FINAL.value:
            return None
        episode.metadata_is_final = False
        return _watched_episode(episode)

    item = run_write_transaction(follow_again)
    if item is None:
        return SweepResult()
    return SweepResult(_refresh(s, [item], now))
