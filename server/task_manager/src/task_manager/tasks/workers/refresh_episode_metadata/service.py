from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import Episode
from backend.services.custom_indexes import request_collection_custom_index_reconciliation
from backend.types.dailywire_user_info import DwMembershipLevel
from backend.types.episode_types import EpisodePublishStatus
from backend.utils.episode_publication_timing import (
    invalidate_safe_publication_timing,
)
from sources.dailywire.api.dw_api.client import MiddlewareAPIError, MiddlewareClient
from sources.dailywire.api.records import DwEpisodeDetailRecord
from ...helpers.episodes.events import queue_episode_status_events
from ...helpers.episodes.identifier_reconciliation import reconcile_episode_identifier
from ...helpers.episodes.metadata import update_episode_from_dailywire
from ...helpers.episodes.no_show import is_no_show_today_slug
from ...helpers.episodes.same_episode import PENDING_EPISODE_PUBLISH_STATUSES
from ...helpers.episodes.status import observe_episode_detail, resolve_episode_status
from ...helpers.refreshed_metadata import check_upgrades_after_refresh
from ...helpers.episodes.unusable_media import NoUsableMediaReason, mark_episode_no_usable_media


logger = logging.getLogger(__name__)


def refresh_dailywire_episode(s: Session, episode_id: int) -> Optional[bool]:
    """Look one published Daily Wire episode up again, as the metadata refresh sweep asks.

    True when it was updated as usual, False when it changed hands because it is
    pending again or has no usable media, and None when it was no longer there or
    no longer published by the time The Daily Wire answered. A failed lookup raises.
    """
    episode = s.get(Episode, episode_id)
    if episode is None or episode.publish_status != EpisodePublishStatus.PUBLISHED_FINAL.value:
        return None
    episode_slug = episode.slug
    require_member_exclusive = episode.collection.membership_level not in {
        DwMembershipLevel.FREE.value,
        DwMembershipLevel.HIGHEST_ALLOWED.value,
    }

    # No transaction stays open while The Daily Wire is looked up.
    s.rollback()
    detail = _fetch_episode_from_dailywire(
        episode_slug=episode_slug,
        require_member_exclusive=require_member_exclusive,
    )

    # The episode may have changed during the lookup.
    episode = s.get(Episode, episode_id)
    if episode is None or episode.publish_status != EpisodePublishStatus.PUBLISHED_FINAL.value:
        return None
    refreshed_normally = _refresh_episode_from_dailywire(s, episode, detail)
    request_collection_custom_index_reconciliation(s, episode.collection_id)
    if not refreshed_normally:
        episode.metadata_is_final = False
    s.commit()
    return refreshed_normally


def _no_usable_reason(detail, observed_status: EpisodePublishStatus) -> NoUsableMediaReason:
    if is_no_show_today_slug(detail.slug):
        return NoUsableMediaReason.NO_SHOW_TODAY
    if observed_status is EpisodePublishStatus.SOURCE_PROCESSING:
        return NoUsableMediaReason.PROCESSING_TIMEOUT
    return NoUsableMediaReason.MEDIA_UNUSABLE


def _fetch_episode_from_dailywire(
    *,
    episode_slug: str,
    require_member_exclusive: bool,
) -> DwEpisodeDetailRecord | None:
    """Fetch one Daily Wire snapshot without any database transaction open."""
    client = MiddlewareClient()
    try:
        return client.get_episode_details(
            episode_slug,
            require_member_exclusive=require_member_exclusive,
        )
    except MiddlewareAPIError as exc:
        if exc.status_code != 404:
            raise
        return None


def _refresh_episode_from_dailywire(
    s: Session,
    episode: Episode,
    detail: DwEpisodeDetailRecord | None,
) -> bool:
    """Apply one fetched snapshot; return False when lifecycle ownership transfers."""
    collection = episode.collection
    old_status = episode.publish_status
    if detail is None:
        new_status = EpisodePublishStatus.NO_USABLE_MEDIA
        mark_episode_no_usable_media(s, episode, reason=NoUsableMediaReason.NOT_FOUND)
        invalidate_safe_publication_timing(
            episode,
            published_final=True,
        )
        queue_episode_status_events(
            s,
            episode=episode,
            collection=collection,
            old_status=old_status,
            new_status=new_status,
            was_created=False,
        )
        s.flush()
        return False

    # Observe before mutating the row. A transient HLS/network failure therefore
    # raises and leaves the final episode untouched for normal task retry.
    observed = observe_episode_detail(detail)
    publication_timing_reference = episode.safe_live_ended
    if publication_timing_reference is None:
        publication_timing_reference = detail.published_date
    resolved = resolve_episode_status(
        detail,
        current_status=old_status,
        publication_timing_reference=publication_timing_reference,
        snapshot=observed,
    )
    new_status = resolved.status

    update_episode_from_dailywire(episode, detail)

    if new_status is EpisodePublishStatus.NO_USABLE_MEDIA:
        mark_episode_no_usable_media(
            s,
            episode,
            reason=_no_usable_reason(detail, observed.status),
        )
        invalidate_safe_publication_timing(
            episode,
            published_final=True,
        )
        queue_episode_status_events(
            s,
            episode=episode,
            collection=collection,
            old_status=old_status,
            new_status=new_status,
            was_created=False,
        )
        return False

    if new_status in PENDING_EPISODE_PUBLISH_STATUSES:
        # Explicit scheduled/delayed/live evidence is authoritative even after a
        # row previously reached final. The status event helper owns lifecycle
        # timing invalidation for that transition.
        episode.publish_status = new_status.value
        episode.metadata_is_final = False
        queue_episode_status_events(
            s,
            episode=episode,
            collection=collection,
            old_status=old_status,
            new_status=new_status,
            was_created=False,
        )
        # The pending check sweep follows it again from here.
        s.flush()
        return False

    # Final publication is sticky against weaker inferred countdown/processing
    # snapshots. Identifier corrections remain authoritative metadata changes.
    episode.publish_status = EpisodePublishStatus.PUBLISHED_FINAL.value
    reconcile_episode_identifier(
        s,
        episode,
        detail,
        previous_publish_status=old_status,
    )
    check_upgrades_after_refresh(s, episode)
    s.flush()
    return True
