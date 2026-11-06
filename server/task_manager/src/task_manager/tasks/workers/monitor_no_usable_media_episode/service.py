from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Episode, Collection
from backend.types.dailywire_user_info import DwMembershipLevel
from backend.types.episode_types import EpisodePublishStatus
from config.network import NoInternetConnectionError, is_no_internet_error
from sources import Feature, all_sources
from sources.dailywire.api.dw_api.client import MiddlewareAPIError, MiddlewareClient
from sources.dailywire.auth import DeviceAuthClient
from task_manager.scheduler.results import TaskResult
from ...helpers.episodes.events import queue_episode_status_events
from ...helpers.episodes.identifier_reconciliation import reconcile_episode_identifier
from ...helpers.episodes.metadata import update_episode_from_dailywire
from ...helpers.episodes.no_show import is_no_show_today_slug
from ...helpers.episodes.quarantine import PREVIOUS_IDENTIFIER_META_KEY, restore_quarantined_identifier
from ...helpers.episodes.status import observe_episode_detail, resolve_episode_status
from ...helpers.episodes.unusable_media import (
    NoUsableMediaReason,
    clear_episode_no_usable_media_tracking,
    delete_no_usable_media_episode,
    mark_episode_no_usable_media,
    no_usable_media_incident_expired,
)
from ...helpers.progress import update_progress


logger = logging.getLogger(__name__)
DEFAULT_NO_USABLE_MEDIA_DELETE_AFTER_MINUTES = 4 * 60


def _replacement_for_quarantined_episode(s: Session, episode: Episode) -> Episode | None:
    """Return a healthy row that reclaimed this quarantined row's canonical identifier."""
    previous_identifier = episode.get_meta(PREVIOUS_IDENTIFIER_META_KEY)
    if not previous_identifier:
        return None
    return s.scalar(
        select(Episode).where(
            Episode.collection_id == episode.collection_id,
            Episode.id != episode.id,
            Episode.episode_identifier == previous_identifier,
            Episode.publish_status != EpisodePublishStatus.NO_USABLE_MEDIA.value,
        ).limit(1)
    )


def _reason_for_unusable_detail(detail, observed_status: EpisodePublishStatus) -> NoUsableMediaReason:
    if is_no_show_today_slug(detail.slug):
        return NoUsableMediaReason.NO_SHOW_TODAY
    if observed_status is EpisodePublishStatus.SOURCE_PROCESSING:
        return NoUsableMediaReason.PROCESSING_TIMEOUT
    return NoUsableMediaReason.MEDIA_UNUSABLE


def _membership(collection: Collection) -> bool:
    return collection.membership_level not in {
        DwMembershipLevel.FREE.value,
        DwMembershipLevel.HIGHEST_ALLOWED.value,
    }


def _recover_episode(
    s: Session,
    episode: Episode,
    detail,
    *,
    observed,
    resolved,
) -> bool:
    """Recover a quarantined row from a remote snapshot resolved outside the DB transaction."""
    if is_no_show_today_slug(detail.slug) or not observed.has_usable_media:
        mark_episode_no_usable_media(
            s,
            episode,
            reason=_reason_for_unusable_detail(detail, observed.status),
        )
        return False

    if resolved.status is EpisodePublishStatus.NO_USABLE_MEDIA:
        mark_episode_no_usable_media(
            s,
            episode,
            reason=_reason_for_unusable_detail(detail, observed.status),
        )
        return False

    # Restoring the exact identifier displaced by quarantine is silent. Any
    # additional authoritative Daily Wire correction after that restoration is a
    # real identifier change and must use the normal downstream event path.
    if not restore_quarantined_identifier(s, episode):
        # A replacement already owns the canonical identifier. Preserve both Daily
        # Wire rows, but never expose duplicate logical media.
        mark_episode_no_usable_media(
            s,
            episode,
            reason=NoUsableMediaReason.MEDIA_UNUSABLE,
        )
        return False

    old_status = episode.publish_status
    update_episode_from_dailywire(episode, detail)
    reconcile_episode_identifier(s, episode, detail)
    clear_episode_no_usable_media_tracking(episode)
    episode.publish_status = resolved.status.value
    episode.metadata_is_final = False
    queue_episode_status_events(
        s,
        episode=episode,
        collection=episode.collection,
        old_status=old_status,
        new_status=resolved.status,
        was_created=False,
    )
    # From here the pending check sweep or the metadata refresh sweep follows it.
    s.commit()
    return True


def _target_result(
    *,
    episode_id: int,
    outcome: str,
    recovered_status: EpisodePublishStatus | None,
    episode_slug: str | None,
    verified: int,
    recovered: int,
    removed: int,
) -> TaskResult:
    """Return machine-readable facts for one targeted verification."""
    data: dict[str, str | int] = {
        "episode_id": episode_id,
        "outcome": outcome,
        "verified": verified,
        "recovered": recovered,
        "removed": removed,
    }
    if recovered_status is not None:
        data["publish_status"] = recovered_status.value
    if episode_slug:
        data["episode_slug"] = episode_slug

    return TaskResult(
        summary="No-usable-media episode verification completed",
        data=data,
    )


async def run_monitor_no_usable_media_episode(
    s: Session,
    *,
    collection_id: Optional[int] = None,
    collection_slug: Optional[str] = None,
    episode_id: Optional[int] = None,
    force: bool = False,
    delete_after_minutes: int = DEFAULT_NO_USABLE_MEDIA_DELETE_AFTER_MINUTES,
    progress=None,
) -> TaskResult:
    """Verify quarantined episodes, recover usable media, or delete confirmed 404s."""
    if force and episode_id is None:
        raise ValueError("Early Delete requires a specific episode_id")

    # The pending checks look after the episodes of Sources that have them.
    checked_elsewhere = [source.id for source in all_sources() if source.has(Feature.PENDING_CHECKS)]
    stmt = select(Episode).where(
        Episode.publish_status == EpisodePublishStatus.NO_USABLE_MEDIA.value,
        Episode.source_key.not_in(checked_elsewhere),
    )
    if episode_id is not None:
        stmt = stmt.where(Episode.id == episode_id)
    elif collection_id is not None:
        stmt = stmt.where(Episode.collection_id == collection_id)
    elif collection_slug is not None:
        stmt = stmt.where(Episode.collection.has(slug=collection_slug))

    candidates = list(s.scalars(stmt))
    if not candidates:
        message = "No no-usable-media episodes to verify"
        update_progress(progress, 100, message)
        if episode_id is not None:
            return _target_result(
                episode_id=episode_id,
                outcome="already_resolved",
                recovered_status=None,
                episode_slug=None,
                verified=0,
                recovered=0,
                removed=0,
            )
        return TaskResult(
            summary=message,
            data={"verified": 0, "recovered": 0, "removed": 0},
        )

    candidate_ids = [episode.id for episode in candidates]
    target_slug: str | None = candidates[0].slug if episode_id is not None else None

    # Candidate discovery starts an implicit transaction. Authentication and each
    # Daily Wire/HLS inspection may block for seconds, so never keep that read
    # transaction checked out while waiting on external I/O.
    s.rollback()
    tokens = DeviceAuthClient().get_token()
    access_token = tokens.access_token if tokens else None
    client = MiddlewareClient(access_token=access_token)
    now = datetime.now(timezone.utc)
    removed = recovered = verified = 0
    target_outcome: str | None = None
    target_recovered_status: EpisodePublishStatus | None = None

    for index, candidate_id in enumerate(candidate_ids, start=1):
        episode = s.get(Episode, candidate_id)
        if episode is None:
            continue

        is_target = episode_id == episode.id
        episode_slug = episode.slug
        safe_live_ended = episode.safe_live_ended
        require_member_exclusive = _membership(episode.collection)
        s.rollback()

        if require_member_exclusive and access_token is None:
            logger.warning("Cannot verify premium episode %s without a valid token", episode_slug)
            if is_target:
                target_outcome = "unverified"
            continue

        try:
            detail = client.get_episode_details(
                episode_slug,
                require_member_exclusive=require_member_exclusive,
            )
        except MiddlewareAPIError as exc:
            # Once the host itself is offline, trying every quarantined episode only
            # creates duplicate failures and keeps a DB-backed worker occupied longer.
            if is_no_internet_error(exc):
                s.rollback()
                raise NoInternetConnectionError() from exc
            if exc.status_code != 404:
                logger.warning("Could not verify no-usable-media episode %s: %s", episode_slug, exc)
                if is_target:
                    target_outcome = "unverified"
                continue
            episode = s.get(Episode, candidate_id)
            if episode is None:
                continue
            verified += 1
            mark_episode_no_usable_media(
                s,
                episode,
                reason=NoUsableMediaReason.NOT_FOUND,
                now=now,
            )
            s.commit()
            if force or no_usable_media_incident_expired(episode, now=now, minutes=delete_after_minutes):
                replacement = _replacement_for_quarantined_episode(s, episode) if is_target else None
                replacement_status = (
                    EpisodePublishStatus(replacement.publish_status)
                    if replacement is not None
                    else None
                )
                replacement_slug = replacement.slug if replacement is not None else None
                logger.info("Deleting confirmed-404 episode %s", episode.slug)
                was_deleted = delete_no_usable_media_episode(s, episode)
                if was_deleted:
                    removed += 1
                if is_target:
                    target_outcome = (
                        ("replaced" if replacement is not None else "deleted")
                        if was_deleted
                        else "retained"
                    )
                    target_recovered_status = replacement_status
                    target_slug = replacement_slug
            elif is_target:
                target_outcome = "retained"
        else:
            # Media inspection can fetch HLS manifests. Resolve it before
            # reacquiring the ORM row so the connection stays available to API
            # traffic during that external request.
            observed = observe_episode_detail(detail, inspect_static_media=True)
            publication_timing_reference = safe_live_ended
            if publication_timing_reference is None:
                publication_timing_reference = detail.published_date
            resolved = resolve_episode_status(
                detail,
                publication_timing_reference=publication_timing_reference,
                snapshot=observed,
            )
            episode = s.get(Episode, candidate_id)
            if episode is None:
                continue
            verified += 1
            try:
                if _recover_episode(
                    s,
                    episode,
                    detail,
                    observed=observed,
                    resolved=resolved,
                ):
                    recovered += 1
                    if is_target:
                        target_outcome = "recovered"
                        target_recovered_status = EpisodePublishStatus(episode.publish_status)
                        target_slug = episode.slug
                else:
                    s.commit()
                    if is_target:
                        target_outcome = "retained"
                        target_slug = episode.slug
            except Exception as exc:
                s.rollback()
                if is_no_internet_error(exc):
                    raise NoInternetConnectionError() from exc
                logger.exception(
                    "Could not verify media usability for episode %s; leaving it quarantined",
                    episode.slug,
                )
                if is_target:
                    target_outcome = "unverified"

        update_progress(
            progress,
            int(index / len(candidate_ids) * 100),
            f"Verified {index}/{len(candidate_ids)} no-usable-media episode(s); recovered {recovered}, removed {removed}",
        )

    message = (
        f"Verified {len(candidate_ids)} no-usable-media episode(s); "
        f"recovered {recovered}, removed {removed}"
    )
    update_progress(progress, 100, message)

    if episode_id is not None:
        return _target_result(
            episode_id=episode_id,
            outcome=target_outcome or "already_resolved",
            recovered_status=target_recovered_status,
            episode_slug=target_slug,
            verified=verified,
            recovered=recovered,
            removed=removed,
        )

    return TaskResult(
        summary=message,
        data={"verified": verified, "recovered": recovered, "removed": removed},
    )
