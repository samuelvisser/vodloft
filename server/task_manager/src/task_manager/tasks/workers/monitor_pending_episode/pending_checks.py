"""Following upcoming and live episodes of Sources with ``Feature.PENDING_CHECKS``, such as yt-dlp.

The Daily Wire's episodes get a monitor job each. These episodes are swept
instead, like the metadata refresh does: the sweep runs every couple of minutes
and looks up the episodes that are due, through ``Source.check_pending``.

- An upcoming episode is looked up every hour, and often from 15 minutes before
  it is due to start until it goes live. One that is more than an hour late is
  back to every hour, because some channels keep a stream waiting for days.
- A live episode, and one the site is still processing, is looked up every few minutes.
- Once it is published it is downloaded like any other episode, and the metadata
  refresh follows it from then on. In a date-based collection it moves to the
  date it was actually published.
- One the Source no longer has, such as a cancelled stream, has no usable media,
  like a Daily Wire episode that is gone. It is looked up every hour in case it
  comes back, and deleted after the same grace period. A lookup that fails for
  another reason is just tried again later.

Nothing is stored per episode: the sweep remembers when it last looked each one
up, so after a restart every one of them is looked up once.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.datetime_types import utc_datetime
from backend.db.models import Episode
from backend.types.episode_types import PENDING_EPISODE_PUBLISH_STATUSES, EpisodePublishStatus
from config import get_settings
from sources import Feature, ItemRef, VideoDetails, all_sources, get_source
from ...helpers.episodes.events import queue_episode_status_events
from ...helpers.episodes.quarantine import restore_quarantined_identifier
from ...helpers.episodes.trusted_publication_timing import track_monitor_publication_timing
from ...helpers.episodes.unusable_media import (
    NoUsableMediaReason,
    clear_episode_no_usable_media_tracking,
    delete_no_usable_media_episode,
    mark_episode_no_usable_media,
    no_usable_media_incident_expired,
)
from ...helpers.listed_collections import date_based_identifier
from ...helpers.refreshed_metadata import apply_refreshed_details

logger = logging.getLogger(__name__)

HOURLY = timedelta(hours=1)
OFTEN = timedelta(minutes=2)
WHILE_LIVE = timedelta(minutes=5)
SOON = timedelta(minutes=15)
LATE = timedelta(hours=1)

_FOLLOWED = [status.value for status in PENDING_EPISODE_PUBLISH_STATUSES] + [EpisodePublishStatus.NO_USABLE_MEDIA.value]
_last_checked: dict[int, datetime] = {}


def interval(status: str, scheduled: Optional[datetime], now: datetime) -> timedelta:
    """How long an episode waits between lookups."""
    if status in {EpisodePublishStatus.LIVE.value, EpisodePublishStatus.SOURCE_PROCESSING.value}:
        return WHILE_LIVE
    if status in {EpisodePublishStatus.SCHEDULED.value, EpisodePublishStatus.DELAYED.value} and scheduled is not None:
        if scheduled - SOON <= now <= scheduled + LATE:
            return OFTEN
    return HOURLY


def is_due(status: str, scheduled: Optional[datetime], last: Optional[datetime], now: datetime) -> bool:
    """Due after its interval, and also right when an upcoming episode is about to start."""
    if last is None:
        return True
    if scheduled is not None and last < scheduled - SOON <= now:
        return True
    return now - last >= interval(status, scheduled, now)


@dataclass(frozen=True)
class _Pending:
    id: int
    source_key: str
    ref: ItemRef


@dataclass
class PendingCheckResult:
    checked: int = 0
    changed: int = 0
    published: int = 0
    gone: int = 0
    recovered: int = 0
    deleted: int = 0
    failed: int = 0

    def summary(self) -> str:
        if not self.checked:
            return "No upcoming or live episode is due for a check"
        text = f"Checked {self.checked} upcoming or live episodes: {self.changed} changed status, {self.published} published"
        if self.gone:
            text += f", {self.gone} no longer at the Source"
        if self.recovered:
            text += f", {self.recovered} back"
        if self.deleted:
            text += f", {self.deleted} deleted"
        if self.failed:
            text += f", {self.failed} could not be checked"
        return text

    def as_data(self) -> dict:
        return vars(self)


def _due(s: Session, source_keys: list[str], now: datetime) -> list[_Pending]:
    rows = s.execute(
        select(Episode.id, Episode.source_key, Episode.source_slug, Episode.sharing_url, Episode.publish_status,
               Episode.scheduled_date)
        .where(Episode.source_key.in_(source_keys), Episode.publish_status.in_(_FOLLOWED))
        .order_by(Episode.id)
    ).all()
    # A published or deleted episode is no longer followed.
    for episode_id in set(_last_checked) - {row[0] for row in rows}:
        del _last_checked[episode_id]
    due = []
    for episode_id, source_key, slug, url, status, scheduled in rows:
        scheduled = utc_datetime(scheduled) if scheduled is not None else None
        if is_due(status, scheduled, _last_checked.get(episode_id), now):
            due.append(_Pending(episode_id, source_key, ItemRef(slug, url)))
    return due


def _check(source_key: str, refs: list[ItemRef]):
    try:
        return get_source(source_key).check_pending(refs)
    except Exception:
        logger.warning("Could not check %d upcoming or live episodes", len(refs), exc_info=True)
        return None


def _move_to_published_date(s: Session, episode: Episode, details: VideoDetails) -> None:
    """An upcoming video often starts later than planned; it keeps the date it was published."""
    if details.published_at is None:
        return
    episode.published_date = details.published_at
    identifier = date_based_identifier(s, episode, details.published_at)
    if identifier is not None:
        # Nothing was downloaded before publication, so no file has the old identifier.
        episode.episode_identifier = identifier


def _apply(s: Session, episode: Episode, details: VideoDetails, result: PendingCheckResult, now: datetime) -> None:
    old_status = episode.publish_status
    new_status = details.publish_status
    apply_refreshed_details(episode, details)
    episode.removed_from_source = False
    if old_status == EpisodePublishStatus.NO_USABLE_MEDIA.value:
        clear_episode_no_usable_media_tracking(episode)
        restore_quarantined_identifier(s, episode)
        result.recovered += 1
    if details.scheduled_at is not None:
        episode.scheduled_date = details.scheduled_at
    if new_status is EpisodePublishStatus.LIVE and episode.went_live_date is None:
        episode.went_live_date = now
    if new_status in PENDING_EPISODE_PUBLISH_STATUSES:
        episode.publish_status = new_status.value
    else:
        _move_to_published_date(s, episode, details)
        episode.publish_status = new_status.value
        episode.drm_protected = details.drm_protected
        # The metadata refresh follows it from now on.
        episode.metadata_is_final = False
        result.published += 1
    if old_status != new_status.value:
        result.changed += 1
        track_monitor_publication_timing(episode, old_status=old_status, new_status=new_status, observed_at=now)
        queue_episode_status_events(
            s, episode=episode, collection=episode.collection, old_status=old_status, new_status=new_status,
            was_created=False,
        )


def _gone(s: Session, episode: Episode, result: PendingCheckResult, now: datetime) -> None:
    old_status = episode.publish_status
    episode.removed_from_source = True
    if old_status != EpisodePublishStatus.NO_USABLE_MEDIA.value:
        mark_episode_no_usable_media(s, episode, reason=NoUsableMediaReason.NOT_FOUND, now=now)
        result.gone += 1
        queue_episode_status_events(
            s, episode=episode, collection=episode.collection, old_status=old_status,
            new_status=EpisodePublishStatus.NO_USABLE_MEDIA, was_created=False,
        )
        return
    minutes = get_settings().episode_status_timing.no_usable_media_delete_after_minutes
    if no_usable_media_incident_expired(episode, now=now, minutes=minutes):
        if delete_no_usable_media_episode(s, episode):
            result.deleted += 1


def run_pending_checks(s: Session, *, now: Optional[datetime] = None) -> PendingCheckResult:
    now = utc_datetime(now or datetime.now(timezone.utc))
    source_keys = [source.id for source in all_sources() if source.has(Feature.PENDING_CHECKS)]
    due = _due(s, source_keys, now)
    # No transaction stays open while the Sources look episodes up.
    s.rollback()
    answers = {
        source_key: _check(source_key, [item.ref for item in due if item.source_key == source_key])
        for source_key in dict.fromkeys(item.source_key for item in due)
    }

    result = PendingCheckResult()
    for item in due:
        _last_checked[item.id] = now
        result.checked += 1
        answer = answers[item.source_key]
        episode = s.get(Episode, item.id)
        if episode is None:
            continue
        if answer is not None and item.ref.slug in answer.removed:
            _gone(s, episode, result, now)
        elif answer is not None and (details := answer.details.get(item.ref.slug)) is not None:
            _apply(s, episode, details, result, now)
        else:
            result.failed += 1
        s.commit()
    return result
