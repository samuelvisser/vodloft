from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.core import run_write_transaction
from backend.db.models import Episode
from backend.db.models.media_download import EpisodeMediaDownload
from backend.services.media_download_history import record_media_download_history
from backend.services.sites import collection_site
from backend.services.upgrade_check import (
    checks_profile, kept_length, next_upgrade_check_at, sponsorblock_categories, upgrade_findings,
)
from backend.types.download_profile_types import MediaDownloadArtifactStatus, UpgradeResult
from backend.types.media_download_history_types import MediaDownloadHistoryAction
from config.network import is_no_internet_error
from sources import get_source
from task_manager.scheduler.results import TaskResult
from task_manager.scheduler.types import OperationSource
from task_manager.tasks.media_download_operations import (
    create_media_download_operation,
    dispatch_queued_media_download_operations,
    get_active_media_download_operation,
)

logger = logging.getLogger(__name__)

_CHECKS_PER_RUN = 25
"""Each check asks the site about one video; the rest wait for the next hourly run."""
_RETRY_AFTER = timedelta(days=1)
"""A check that could not ask the site, or found the episode busy, tries again this much later."""


def run_upgrade_checks(s: Session, *, now: datetime | None = None) -> TaskResult:
    """Check the downloads whose upgrade check is due, and download again those that can be better."""
    now = now or datetime.now(timezone.utc)
    due = list(s.scalars(
        select(EpisodeMediaDownload.id)
        .where(
            EpisodeMediaDownload.upgrade_check_at.is_not(None),
            EpisodeMediaDownload.upgrade_check_at <= now,
        )
        .order_by(EpisodeMediaDownload.upgrade_check_at)
        .limit(_CHECKS_PER_RUN)
    ))
    s.rollback()
    checked = upgraded = 0
    for download_id in due:
        result = _check(s, download_id, now)
        if result is not None:
            checked += 1
            upgraded += result == UpgradeResult.UPGRADED
    run_write_transaction(dispatch_queued_media_download_operations)
    return TaskResult(
        summary=f"Checked {checked} download(s), {upgraded} can be better" if checked else "No upgrade checks were due",
        data={"checked": checked, "upgraded": upgraded},
    )


def _site(download: EpisodeMediaDownload):
    """The download's Site when its upgrade check still applies, else None."""
    profile = download.download_profile
    episode = download.media
    source = get_source(episode.source_key) if isinstance(episode, Episode) else None
    site = collection_site(episode.collection) if source is not None else None
    if (
        profile is None or site is None or not profile.enable_profile or not checks_profile(site, profile)
        or download.artifact_status != MediaDownloadArtifactStatus.AVAILABLE.value
    ):
        return None
    return site


def _check_later(download_id: int, when: datetime | None) -> None:
    def work(w: Session) -> None:
        download = w.get(EpisodeMediaDownload, download_id)
        if download is not None:
            download.upgrade_check_at = when

    run_write_transaction(work)


def _check(s: Session, download_id: int, now: datetime) -> UpgradeResult | None:
    """Ask the site about one download, then record what it offered in a short write."""
    download = s.get(EpisodeMediaDownload, download_id)
    if download is None:
        s.rollback()
        return None
    if _site(download) is None:
        s.rollback()
        _check_later(download_id, None)
        return None
    if get_active_media_download_operation(s, download.id) is not None:
        s.rollback()
        _check_later(download_id, now + _RETRY_AFTER)
        return None

    episode = download.media
    source = get_source(episode.source_key)
    url, categories = episode.sharing_url, sponsorblock_categories(download.download_profile)
    s.rollback()
    try:
        offer = source.upgrade_offer(url, sponsorblock_categories=categories)
    except Exception as exc:
        if is_no_internet_error(exc):
            raise
        logger.info("Could not check %s for a better version: %s", url, exc)
        _check_later(download_id, now + _RETRY_AFTER)
        return None
    return run_write_transaction(lambda w: _record_offer(w, download_id, offer, now))


def _record_offer(s: Session, download_id: int, offer, now: datetime) -> UpgradeResult | None:
    download = s.get(EpisodeMediaDownload, download_id)
    if download is None or download.download_profile is None:
        return None
    site = _site(download)
    if site is None:
        download.upgrade_check_at = None
        return None
    profile = download.download_profile
    findings = upgrade_findings(offer, download, profile, download.local_media_profile, site)
    download.upgrade_checks += 1
    download.upgrade_check_at = (
        next_upgrade_check_at(profile, download.upgrade_checks, now) if findings.could_improve else None
    )
    result = UpgradeResult.UPGRADED if findings.improvements else UpgradeResult.CHECKED
    download.upgrade_result = result.value
    record_media_download_history(
        s, download.id, MediaDownloadHistoryAction.UPGRADE_CHECKED,
        metadata={
            "improvements": [improvement.value for improvement in findings.improvements],
            "best_height": findings.best_height,
            "kept_height": download.video_height,
            "offered_duration": offer.duration,
            "kept_duration": kept_length(download),
        },
        occurred_at=now,
    )
    if findings.improvements:
        create_media_download_operation(
            s, download, source=OperationSource.SYSTEM.value, is_redownload=True, prepare_existing_artifact=True,
        )
    return result
