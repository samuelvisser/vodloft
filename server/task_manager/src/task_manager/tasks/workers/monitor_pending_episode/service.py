from __future__ import annotations

import logging
from sqlalchemy.orm import Session

from backend.db.models import Episode, Collection
from backend.types.dailywire_user_info import DwMembershipLevel
from backend.types.episode_types import EpisodePublishStatus
from backend.utils.episode_publication_timing import best_effort_published_date
from sources.dailywire.api.dw_api.client import ByShowSeason, MiddlewareAPIError, MiddlewareClient

from ._helpers import save_status_metadata
from backend.services.metadata_refresh import refresh_watch_expired
from ...helpers.episodes.trusted_publication_timing import track_monitor_publication_timing
from ...helpers.episodes.events import queue_episode_status_events
from ...helpers.episodes.identifier_reconciliation import reconcile_episode_identifier
from ...helpers.episodes.mapper import fetch_all_episodes_paginated
from ...helpers.episodes.metadata import (
    episode_refresh_offsets,
    update_episode_from_dailywire,
)
from ...helpers.episodes.no_show import is_no_show_today_slug
from ...helpers.episodes.same_episode import (
    PENDING_EPISODE_PUBLISH_STATUSES,
    reconcile_single_pending_episode_slug,
)
from ...helpers.episodes.status import observe_episode_detail, resolve_episode_status
from ...helpers.episodes.unusable_media import (
    NoUsableMediaReason,
    clear_episode_no_usable_media_tracking,
    mark_episode_no_usable_media,
)


logger = logging.getLogger(__name__)


def _membership_plan(collection: Collection) -> tuple[str, bool]:
    membership_plan = collection.membership_level
    if membership_plan == DwMembershipLevel.HIGHEST_ALLOWED.value:
        return DwMembershipLevel.FREE.value, False
    return membership_plan, membership_plan != DwMembershipLevel.FREE.value


def _reload_episode_and_collection(
    s: Session,
    *,
    episode_id: int,
    collection_id: int,
) -> tuple[Episode, Collection]:
    collection = s.get(Collection, collection_id)
    episode = s.get(Episode, episode_id)
    if collection is None or episode is None:
        raise ValueError("Pending episode or collection was removed while it was being refreshed")
    return episode, collection


def _try_reconcile_slug_after_404(
    s: Session,
    *,
    client: MiddlewareClient,
    collection: Collection,
    episode: Episode,
) -> str | None:
    """Try the same conservative pending-slug reconciliation used by discovery.

    Remote requests deliberately run outside a database transaction, so no
    connection stays checked out while The Daily Wire is slow or offline.
    """
    membership_plan, _ = _membership_plan(collection)
    collection_id = collection.id
    episode_id = episode.id
    collection_slug = collection.slug
    season_slug = episode.season.slug
    s.rollback()

    collection_page = client.get_show_page(collection_slug, membership_plan=membership_plan)
    remote_season = next(
        (candidate for candidate in collection_page.seasons if candidate.slug == season_slug),
        None,
    )
    if remote_season is None:
        return None

    records = fetch_all_episodes_paginated(
        client,
        collection_slug,
        ByShowSeason(
            season_dw_id=remote_season.dw_id,
            membership_plan=membership_plan,
            page_size=50,
            order_by="CreatedAt_ASC",
        ),
    )

    episode, collection = _reload_episode_and_collection(
        s,
        episode_id=episode_id,
        collection_id=collection_id,
    )
    reconciled = reconcile_single_pending_episode_slug(
        s,
        collection=collection,
        season=episode.season,
        remote_records=records,
    )
    if reconciled is None or reconciled.id != episode.id:
        s.rollback()
        return None

    reconciled_slug = reconciled.slug
    s.commit()
    return reconciled_slug


def _no_usable_reason(detail, *, observed_status: EpisodePublishStatus) -> NoUsableMediaReason:
    if is_no_show_today_slug(detail.slug):
        return NoUsableMediaReason.NO_SHOW_TODAY
    if observed_status is EpisodePublishStatus.SOURCE_PROCESSING:
        return NoUsableMediaReason.PROCESSING_TIMEOUT
    return NoUsableMediaReason.MEDIA_UNUSABLE


def _quarantine_404(
    s: Session,
    *,
    episode: Episode,
    collection: Collection,
    old_status: str,
) -> EpisodePublishStatus:
    new_status = EpisodePublishStatus.NO_USABLE_MEDIA
    mark_episode_no_usable_media(
        s,
        episode,
        reason=NoUsableMediaReason.NOT_FOUND,
    )
    track_monitor_publication_timing(
        episode,
        old_status=old_status,
        new_status=new_status,
    )
    queue_episode_status_events(
        s,
        episode=episode,
        collection=collection,
        old_status=old_status,
        new_status=new_status,
        was_created=False,
    )
    s.commit()
    logger.info(
        "Daily Wire returned 404 for pending episode %s; status %s -> %s",
        episode.id,
        old_status,
        new_status.value,
    )
    return new_status


def run_monitor_pending_episode(s: Session, *, episode_id: int) -> EpisodePublishStatus:
    """Look one pending Daily Wire episode up, and hand it over once it is published or gone."""
    episode = s.get(Episode, episode_id)
    if episode is None:
        raise ValueError(f"Pending episode {episode_id} was removed before it was checked")
    collection = episode.collection

    old_status = episode.publish_status
    if old_status not in PENDING_EPISODE_PUBLISH_STATUSES:
        s.rollback()
        return EpisodePublishStatus(old_status)

    episode_db_id = episode.id
    collection_db_id = collection.id
    request_slug = episode.slug
    _, require_member_exclusive = _membership_plan(collection)
    client = MiddlewareClient()

    # A SELECT starts an ORM transaction. Release it before DNS/HTTP/HLS work so
    # no transaction stays open while The Daily Wire is looked up.
    s.rollback()
    try:
        detail = client.get_episode_details(
            request_slug,
            require_member_exclusive=require_member_exclusive,
        )
    except MiddlewareAPIError as exc:
        if exc.status_code != 404:
            raise

        episode, collection = _reload_episode_and_collection(
            s,
            episode_id=episode_db_id,
            collection_id=collection_db_id,
        )
        reconciled_slug = _try_reconcile_slug_after_404(
            s,
            client=client,
            collection=collection,
            episode=episode,
        )
        if reconciled_slug is None:
            episode, collection = _reload_episode_and_collection(
                s,
                episode_id=episode_db_id,
                collection_id=collection_db_id,
            )
            return _quarantine_404(
                s,
                episode=episode,
                collection=collection,
                old_status=episode.publish_status,
            )

        try:
            detail = client.get_episode_details(
                reconciled_slug,
                require_member_exclusive=require_member_exclusive,
            )
        except MiddlewareAPIError as reconciled_exc:
            if reconciled_exc.status_code != 404:
                raise
            episode, collection = _reload_episode_and_collection(
                s,
                episode_id=episode_db_id,
                collection_id=collection_db_id,
            )
            return _quarantine_404(
                s,
                episode=episode,
                collection=collection,
                old_status=episode.publish_status,
            )

    # Media inspection can itself fetch HLS manifests. Keep that I/O outside the
    # ORM transaction, then reload current rows before recording trusted facts.
    observed = observe_episode_detail(detail)

    episode, collection = _reload_episode_and_collection(
        s,
        episode_id=episode_db_id,
        collection_id=collection_db_id,
    )
    old_status = episode.publish_status
    if old_status not in PENDING_EPISODE_PUBLISH_STATUSES:
        s.rollback()
        return EpisodePublishStatus(old_status)

    # Record the observed publication timing before applying status fallbacks.
    track_monitor_publication_timing(
        episode,
        old_status=old_status,
        new_status=observed.status,
    )
    publication_timing_reference = episode.safe_live_ended
    if publication_timing_reference is None:
        publication_timing_reference = detail.published_date
    resolved = resolve_episode_status(
        detail,
        publication_timing_reference=publication_timing_reference,
        snapshot=observed,
    )
    new_status = resolved.status

    update_episode_from_dailywire(episode, detail)
    if new_status is EpisodePublishStatus.NO_USABLE_MEDIA:
        mark_episode_no_usable_media(
            s,
            episode,
            reason=_no_usable_reason(detail, observed_status=observed.status),
        )
    else:
        episode.publish_status = new_status
        clear_episode_no_usable_media_tracking(episode)

    if new_status is not EpisodePublishStatus.NO_USABLE_MEDIA:
        final_publication_time = best_effort_published_date(episode)
        episode.metadata_is_final = (
            refresh_watch_expired(final_publication_time, episode_refresh_offsets(episode))
            if new_status is EpisodePublishStatus.PUBLISHED_FINAL
            else False
        )
        reconcile_episode_identifier(
            s,
            episode,
            detail,
            previous_publish_status=old_status,
        )

    if new_status in PENDING_EPISODE_PUBLISH_STATUSES:
        save_status_metadata(
            s,
            episode=episode,
            dw_episode=detail,
            status=new_status,
        )
    # Once published, the metadata refresh sweep follows it until its metadata is final.

    track_monitor_publication_timing(
        episode,
        old_status=old_status,
        new_status=new_status,
    )
    queue_episode_status_events(
        s,
        episode=episode,
        collection=collection,
        old_status=old_status,
        new_status=new_status,
        was_created=False,
    )
    s.commit()

    logger.info("Episode %s status: %s -> %s", episode.id, old_status, new_status.value)
    return new_status
