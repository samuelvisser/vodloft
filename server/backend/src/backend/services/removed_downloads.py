"""Downloads whose episode the Source no longer has: VODLoft asks whether to keep them.

When an episode VODLoft downloaded disappears from its Source, the file on disk may be the
only copy left. The Home page then asks whether to keep the download. Until the person
answers, retention never deletes it, whatever the Download Profile's date lines say.
Keep marks the download as kept by hand; Don't keep only records the answer, so retention
treats it like any other download from then on.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from backend.db.models import EpisodeMediaDownload, Episode
from backend.types.download_profile_types import MediaDownloadArtifactStatus


def _open(download) -> bool:
    return (
        not download.kept
        and download.removal_answered_at is None
        and download.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value
    )


def awaits_keep_answer(download, *, removed_from_source: bool) -> bool:
    """Whether the Home page asks about this download, so retention must leave it alone."""
    return removed_from_source and _open(download)


def _awaiting():
    return and_(
        Episode.removed_from_source.is_(True),
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
    return len(downloads)
