from __future__ import annotations

import logging
from sqlalchemy.orm import Session

from sources import FREE_LEVEL, HIGHEST_LEVEL
from backend.db.models import Episode, Collection
from backend.db.core import run_write_transaction
from backend.types.episode_types import EpisodePublishStatus
from backend.utils.episode_publication_timing import best_effort_published_date
from sources.dailywire.api.dw_api.client import ByShowSeason, MiddlewareAPIError, MiddlewareClient

from ._helpers import save_status_metadata
from backend.services.metadata_refresh import refresh_watch_expired
from backend.services.removed_downloads import back_at_source, left_source
from ...helpers.episodes.trusted_publication_timing import track_monitor_publication_timing
from ...helpers.episodes.events import queue_episode_status_events
from ...helpers.episodes.identifier_reconciliation import reconcile_episode_identifier
from backend.services.episode_numbering import Numbering
from sources.dailywire.source import video_of
from ...helpers.episodes.metadata import (
    episode_refresh_offsets,
    update_episode_from_dailywire,
)
from ...helpers.episodes.same_episode import (
    PENDING_EPISODE_PUBLISH_STATUSES,
    reconcile_single_pending_episode_slug,
)
from sources.dailywire.status import observe_episode_detail, resolve_episode_status


logger = logging.getLogger(__name__)


def _numbering(episode: Episode, detail) -> Numbering:
    """What numbers the episode, from The Daily Wire's details of it now."""
    return Numbering.of_video(video_of(detail, season_name=episode.season.name), detail.published_date)


def _membership_plan(collection: Collection) -> tuple[str, bool]:
    membership_plan = collection.membership_level
    if membership_plan == HIGHEST_LEVEL:
        return FREE_LEVEL, False
    return membership_plan, membership_plan != FREE_LEVEL


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

    records = client.get_all_episodes(
        collection_slug,
        ByShowSeason(
            season_dw_id=remote_season.dw_id,
            membership_plan=membership_plan,
            page_size=50,
            order_by="CreatedAt_ASC",
        ),
    )

    def store(s: Session) -> str | None:
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

        return reconciled.slug

    return run_write_transaction(store)


def _not_found(*, episode_id: int, collection_id: int) -> None:
    """The Daily Wire no longer knows the pending episode: it left the Source."""
    def store(s: Session) -> bool:
        episode, _collection = _reload_episode_and_collection(s, episode_id=episode_id, collection_id=collection_id)
        return left_source(s, episode)

    deleted = run_write_transaction(store)
    logger.info(
        "Daily Wire returned 404 for pending episode %s; %s",
        episode_id,
        "deleted it" if deleted else "marked it removed",
    )


def run_monitor_pending_episode(s: Session, *, episode_id: int) -> EpisodePublishStatus | None:
    """Look one pending Daily Wire episode up, and hand it over once it is published.

    Returns its new status, or None when The Daily Wire no longer has it or has nothing usable for it: then it is
    marked removed from its Source, and deleted once it has waited long enough without files."""
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
            _not_found(episode_id=episode_db_id, collection_id=collection_db_id)
            return None

        try:
            detail = client.get_episode_details(
                reconciled_slug,
                require_member_exclusive=require_member_exclusive,
            )
        except MiddlewareAPIError as reconciled_exc:
            if reconciled_exc.status_code != 404:
                raise
            _not_found(episode_id=episode_db_id, collection_id=collection_db_id)
            return None

    # Media inspection can itself fetch HLS manifests. Keep that I/O outside the
    # ORM transaction, then reload current rows before recording trusted facts.
    observed = observe_episode_detail(detail)

    def record(s: Session) -> tuple[EpisodePublishStatus | None, str | None]:
        episode, collection = _reload_episode_and_collection(
            s,
            episode_id=episode_db_id,
            collection_id=collection_db_id,
        )
        old_status = episode.publish_status
        if old_status not in PENDING_EPISODE_PUBLISH_STATUSES:
            # Something else handed it over meanwhile.
            return EpisodePublishStatus(old_status), None

        if observed.status is not None:
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
        if new_status is None:
            # Nothing usable, such as a recording that never finished processing.
            left_source(s, episode)
            return None, old_status

        episode.publish_status = new_status
        back_at_source(episode)
        final_publication_time = best_effort_published_date(episode)
        episode.metadata_is_final = (
            refresh_watch_expired(final_publication_time, episode_refresh_offsets(episode))
            if new_status is EpisodePublishStatus.PUBLISHED_FINAL
            else False
        )
        reconcile_episode_identifier(
            s,
            episode,
            _numbering(episode, detail),
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
        return new_status, old_status

    new_status, old_status = run_write_transaction(record)
    if old_status is not None:
        logger.info(
            "Episode %s status: %s -> %s", episode_db_id, old_status,
            "removed from its Source" if new_status is None else new_status.value,
        )
    return new_status
