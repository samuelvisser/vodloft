"""Episodes the Source no longer has, and their downloads: VODLoft asks whether to keep them.

An episode the Source no longer has, or has nothing usable for, such as a Daily Wire episode that was taken down
or a cancelled stream, goes when it has no files. One that went live and was not published yet first gets a few
hours, on every Site: right after a stream, the Source may not show it for a while. A downloaded episode stays,
marked removed from its Source.

When an episode VODLoft downloaded disappears from its Source, the file on disk may be the
only copy left. The Home page then asks whether to keep the download. Until the person
answers, retention never deletes it, whatever the Download Profile's date lines say.
Keep marks the download as kept by hand; Don't keep only records the answer, so retention
treats it like any other download from then on.

On a Site that removes its media itself after a while, such as Twitch with its past broadcasts, an episode that goes
once it is older than the least time the Site keeps media is removed by the Site's retention: VODLoft expected it to
go, so Home does not ask about its downloads. One that goes sooner is missing, as on any other Site.

A video a collection only had because one of its link seasons listed it, which the creator then took out of that
playlist, is asked about the same way. Don't keep then removes it from the collection, files and all.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from backend.db.models import EpisodeMediaDownload, Episode
from backend.db.datetime_types import utc_datetime
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.episode_types import PENDING_EPISODE_PUBLISH_STATUSES, EpisodePublishStatus

AFTER_LIVE_WAIT = timedelta(hours=4)
"""How long an episode that went live, and is gone before it was published, stays without files."""
_GONE_SINCE = "removed_from_source.since"
_AFTER_LIVE = {
    status.value for status in PENDING_EPISODE_PUBLISH_STATUSES
    if status not in {EpisodePublishStatus.SCHEDULED, EpisodePublishStatus.DELAYED}
}


def left_source(s: Session, episode: Episode, *, now: datetime | None = None) -> bool:
    """The Source no longer has this episode. Returns whether it was deleted.

    ``s`` is a write transaction's session."""
    from backend.services.sites import episode_site

    now = utc_datetime(now or datetime.now(timezone.utc))
    retention = episode_site(episode).retention
    episode.removed_from_source = True
    episode.removed_by_retention = (
        retention is not None and episode.published_date is not None
        and now - utc_datetime(episode.published_date) >= retention.kept_for
    )
    has_files = s.scalar(
        select(EpisodeMediaDownload.id).where(EpisodeMediaDownload.media_item_id == episode.id).limit(1)
    ) is not None
    if has_files:
        return False
    if episode.publish_status in _AFTER_LIVE:
        since = episode.get_meta(_GONE_SINCE)
        if since is None:
            episode.set_meta(_GONE_SINCE, now.isoformat())
            return False
        if now - utc_datetime(datetime.fromisoformat(since)) < AFTER_LIVE_WAIT:
            return False
    delete_episode(s, episode)
    return True


def back_at_source(episode: Episode) -> bool:
    """The Source has this episode again. Returns whether it was marked removed."""
    for item in list(episode.meta_items):
        if item.key == _GONE_SINCE:
            episode.meta_items.remove(item)
    was_removed = episode.removed_from_source
    episode.removed_from_source = False
    episode.removed_by_retention = False
    return was_removed


def delete_episode(s: Session, episode: Episode) -> None:
    """Delete an episode, with its download records.

    ``s`` is a write transaction's session."""
    from backend.services.custom_indexes import request_collection_custom_index_reconciliation
    from task_manager.events.transactional import queue_event

    queue_event(s, "episode.deleted", {
        "resource_id": episode.id, "id": episode.id, "slug": episode.slug, "collection_id": episode.collection_id,
    })
    request_collection_custom_index_reconciliation(s, episode.collection_id)
    s.delete(episode)
    s.flush()


def _open(download) -> bool:
    return (
        not download.kept
        and download.removal_answered_at is None
        and download.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value
    )


def awaits_keep_answer(download, *, removed_from_source: bool, removed_by_retention: bool) -> bool:
    """Whether the Home page asks about this download, so retention must leave it alone. It never asks about media
    the Site's own retention removed."""
    return removed_from_source and not removed_by_retention and _open(download)


def _awaiting():
    return and_(
        Episode.removed_from_source.is_(True),
        Episode.removed_by_retention.is_(False),
        EpisodeMediaDownload.kept.is_(False),
        EpisodeMediaDownload.removal_answered_at.is_(None),
        EpisodeMediaDownload.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value,
    )


def downloads_awaiting_keep_answer(s: Session) -> list[EpisodeMediaDownload]:
    """Every download the Home page asks about, newest download first."""
    return list(s.scalars(
        select(EpisodeMediaDownload)
        .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
        .where(_awaiting())
        .order_by(EpisodeMediaDownload.downloaded_at.desc(), EpisodeMediaDownload.id.desc())
    ))


def answer_keep_question(s: Session, episode_ids: Iterable[int], *, keep: bool) -> int:
    """Answer for every open download of these episodes. Returns how many were answered."""
    ids = list(episode_ids)
    if not ids:
        return 0
    downloads = s.scalars(
        select(EpisodeMediaDownload)
        .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
        .where(_awaiting(), Episode.id.in_(ids))
    ).all()
    now = datetime.now(timezone.utc)
    for download in downloads:
        download.removal_answered_at = now
        if keep:
            download.kept = True
    s.flush()
    if not keep:
        _remove_left(s, {download.media.collection_id for download in downloads if download.media.from_link_season})
    return len(downloads)


def _remove_left(s: Session, collection_ids: set[int]) -> None:
    """Let the videos that left these collections' link seasons go, now that the user doesn't keep their files."""
    from task_manager.scheduler.transactional import queue_task_after_commit

    for collection_id in sorted(collection_ids):
        queue_task_after_commit(s, def_key="remove_left_episodes", resource_type="collection", resource_id=collection_id)
