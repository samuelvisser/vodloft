from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.services.check_frequency import full_scan_done, full_scan_due
from backend.db.models import Episode, Season, Collection
from backend.services.collection_assets import update_collection_artwork_metadata
from backend.services.thumbnails import newest_media_item_id, take_first_frames
from backend.types.dailywire_user_info import DwMembershipLevel
from backend.types.episode_types import EpisodePublishStatus
from backend.types.collection_types import EpisodeIdentifier
from sources.dailywire.api.dw_api.client import ByShowSeason, MiddlewareClient
from sources.dailywire.api.records import DwEpisodeRecord, DwSeasonRecord
from sources.dailywire.auth import DeviceAuthClient
from sources import Feature, Source, get_source
from task_manager.events.transactional import queue_event
from ._helpers import get_latest_ep_index, get_season_from_list_by_id, get_collections
from ...helpers.episodes.events import queue_episode_status_events
from ...helpers.episodes.identifier import IdentifierMaxValues, identify_episodes_in_season
from ...helpers.episodes.mapper import (
    count_total_episodes,
    fetch_all_episodes_paginated,
    fetch_episodes_until_slug,
    get_dw_episodes_since_ep,
)
from ...helpers.episodes.quarantine import vacated_canonical_identifiers_for_collection
from ...helpers.episodes.same_episode import (
    PENDING_EPISODE_PUBLISH_STATUSES,
    reconcile_single_pending_episode_slug,
)
from ...helpers.episodes.save import (
    ResolvedEpisode,
    SavedEpisode,
    resolve_dw_episodes,
    save_resolved_episodes_per_season_asc,
)
from ...helpers.listed_collections import index_listed_collection
from ...helpers.progress import ProgressBounds, update_progress
from ...helpers.seasons import create_season_by_dw_season
from ...types.general import RecordOrder
from ..monitor_pending_episode.scheduling import MONITOR_REQUESTED_EVENT


logger = logging.getLogger(__name__)

COLLECTION_INDEXED_EVENT = "collection.indexed"


def _canonicalize_resolved_identifiers(
    *,
    collection: Collection,
    resolved_by_season: dict[int, list[ResolvedEpisode]],
    previous_values: IdentifierMaxValues,
    occupied_identifiers: set[str],
) -> tuple[dict[int, list[ResolvedEpisode]], IdentifierMaxValues]:
    """Re-run one complete identifier pass over authoritative resolved records.

    Pagination is enough to discover candidate episodes, but getEpisode can refine
    fields such as episodeNumber/isTrailer. Re-identifying the complete batch before
    any row is written prevents one corrected record from temporarily stealing an
    identifier that another record in the same batch is about to vacate.
    """
    values = dict(previous_values)
    occupied = set(occupied_identifiers)
    identifier_type = EpisodeIdentifier(collection.episode_identifier)
    canonical: dict[int, list[ResolvedEpisode]] = {}

    for season_id, resolved_episodes in resolved_by_season.items():
        season = get_season_from_list_by_id(collection.seasons, season_id)
        if season is None:
            continue
        mapped, values = identify_episodes_in_season(
            identifier_type,
            [resolved.record for resolved in resolved_episodes],
            values,
            season=season,
            occupied_identifiers=occupied,
        )
        canonical[season_id] = [
            replace(resolved, episode_identifier=identifier)
            for resolved, (identifier, _record) in zip(
                resolved_episodes,
                mapped,
                strict=True,
            )
        ]

    return canonical, values


@dataclass(frozen=True)
class CollectionEpisodeScanResult:
    collection_id: int
    collection_slug: str
    collection_title: str
    episodes_found: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "collection_slug": self.collection_slug,
            "collection_title": self.collection_title,
            "episodes_found": self.episodes_found,
        }


@dataclass(frozen=True)
class FetchNewEpisodesResult:
    collections: tuple[CollectionEpisodeScanResult, ...]
    dry_run: bool = False

    @property
    def episodes_found(self) -> int:
        return sum(collection.episodes_found for collection in self.collections)

    @property
    def collections_scanned(self) -> int:
        return len(self.collections)

    def summary(self) -> str:
        if self.dry_run:
            return "Dry-run episode scan completed"
        if self.collections_scanned == 1:
            only = self.collections[0]
            return f"Episode scan finished for {only.collection_title}: {only.episodes_found} new {'episode' if only.episodes_found == 1 else 'episodes'} found"
        return f"Episode scan finished for {self.collections_scanned} collections: {self.episodes_found} new {'episode' if self.episodes_found == 1 else 'episodes'} found"

    def as_data(self) -> dict[str, Any]:
        return {
            "episodes_found": self.episodes_found,
            "collections_scanned": self.collections_scanned,
            "collections": [collection.as_dict() for collection in self.collections],
        }


async def run_fetch_new_episodes(
    s: Session,
    *,
    collection_id: Optional[int] = None,
    collection_slug: Optional[str] = None,
    dry_run: bool = False,
    initial_index: bool = False,
    quick_checked: bool | None = None,
    progress=None,
) -> FetchNewEpisodesResult:
    """Scan one collection, or all collections. ``quick_checked`` limits a scan of all collections to the
    collections whose Source has quick checks (True), which get a full re-scan once a day,
    or to the other collections (False)."""
    collections: Sequence[Collection] = get_collections(s, collection_id=collection_id, collection_slug=collection_slug)
    if quick_checked is not None and collection_id is None and not collection_slug:
        collections = [collection for collection in collections if get_source(collection.source_key).has(Feature.QUICK_CHECK) == quick_checked]
    if collection_id is None and not collection_slug:
        # Each Collection's check frequency: on its own schedule it is left out, checked less often it skips scans.
        collections = [collection for collection in collections if full_scan_due(collection)]
    collection_ids = [collection.id for collection in collections]
    lists_episodes = {collection.id: get_source(collection.source_key).has(Feature.EPISODE_LISTS) for collection in collections}

    # Token refresh can itself require the internet. Do not retain the SELECT
    # transaction used to find the collections while waiting for OAuth/DNS/HTTP.
    s.rollback()
    access_token: str | None = None
    client: MiddlewareClient | None = None
    if not all(lists_episodes.values()):
        tokens = DeviceAuthClient().get_token()
        access_token = tokens.access_token if tokens else None
        client = MiddlewareClient(access_token=access_token)
    completed: list[CollectionEpisodeScanResult] = []
    for current_collection_id in collection_ids:
        collection = s.get(Collection, current_collection_id)
        if collection is None:
            continue
        full_scan_done(current_collection_id)
        if lists_episodes[current_collection_id]:
            completed.append(_index_listed_collection(
                s, collection=collection, source=get_source(collection.source_key), dry_run=dry_run, progress=progress,
            ))
            continue
        try:
            found = await _fetch_collection(
                s,
                collection=collection,
                client=client,
                access_token=access_token,
                dry_run=dry_run,
                initial_index=initial_index,
                progress=progress,
            )
        except Exception:
            s.rollback()
            raise
        completed.append(CollectionEpisodeScanResult(
            collection_id=collection.id,
            collection_slug=collection.slug,
            collection_title=collection.title,
            episodes_found=0 if dry_run else found,
        ))
    return FetchNewEpisodesResult(collections=tuple(completed), dry_run=dry_run)


async def _fetch_collection(
    s: Session,
    *,
    collection: Collection,
    client: MiddlewareClient,
    access_token: str | None,
    dry_run: bool,
    initial_index: bool,
    progress=None,
) -> int:
    collection_id = collection.id
    collection_slug = collection.slug
    membership_plan = collection.membership_level
    if membership_plan != DwMembershipLevel.FREE.value and access_token is None:
        if membership_plan != DwMembershipLevel.HIGHEST_ALLOWED.value:
            logger.warning("No valid access token for collection %s", collection_slug)
            return 0
    if membership_plan == DwMembershipLevel.HIGHEST_ALLOWED.value:
        membership_plan = DwMembershipLevel.FREE.value
    require_member_exclusive = membership_plan != DwMembershipLevel.FREE.value

    latest_final_episode = s.execute(
        select(Episode)
        .where(
            Episode.collection_id == collection_id,
            Episode.publish_status == EpisodePublishStatus.PUBLISHED_FINAL.value,
        )
        .order_by(Episode.index.desc())
        .limit(1)
    ).scalar_one_or_none()
    latest_final_episode_id = latest_final_episode.id if latest_final_episode is not None else None
    latest_final_episode_slug = latest_final_episode.slug if latest_final_episode is not None else None
    latest_final_season_id = latest_final_episode.season_id if latest_final_episode is not None else None
    vacated_identifiers = vacated_canonical_identifiers_for_collection(s, collection_id)

    monitor_requests: dict[int, dict] = {
        episode.id: _monitor_request_for_db_episode(collection, episode)
        for episode in s.scalars(select(Episode).where(
            Episode.collection_id == collection_id,
            Episode.publish_status.in_(PENDING_EPISODE_PUBLISH_STATUSES),
        ))
    }

    # The local snapshot is complete. Release its transaction before the first
    # Daily Wire request so an outage cannot pin a DB connection per worker.
    s.rollback()

    dw_show = client.get_show_page(collection_slug, membership_plan=membership_plan)
    all_dw_seasons: list[DwSeasonRecord] = dw_show.seasons

    square_thumbnail_path: str | None = None
    if initial_index and not dry_run:
        square_thumbnail_path = dw_show.thumbnail_square_path
        if square_thumbnail_path is None:
            square_thumbnail_path = client.get_square_show_thumbnails(
                membership_plan=membership_plan,
            ).get(collection_slug)

    collection = s.get(Collection, collection_id)
    if collection is None:
        raise ValueError(f"Collection {collection_id} was removed while it was being indexed")
    if not dry_run:
        update_collection_artwork_metadata(collection, dw_show)
    if initial_index and not dry_run:
        collection.thumbnail_square_path = square_thumbnail_path
    for remote_season in all_dw_seasons:
        if not any(season.slug == remote_season.slug for season in collection.seasons):
            create_season_by_dw_season(s, collection=collection, dw_season=remote_season)
            s.flush()
            s.refresh(collection, attribute_names=["seasons"])
    if not dry_run:
        # Newly discovered seasons are independent local facts and must exist before
        # the network-only prefetch phase. Committing also releases the connection.
        s.commit()

    dw_id_by_slug = {season.slug: season.dw_id for season in all_dw_seasons}
    seasons_to_scan = list(collection.seasons)
    if latest_final_season_id is not None:
        cursor_position = next(
            (
                index
                for index, season in enumerate(seasons_to_scan)
                if season.id == latest_final_season_id
            ),
            None,
        )
        if cursor_position is not None:
            seasons_to_scan = seasons_to_scan[:cursor_position + 1]

    season_requests = [
        (season.id, season.slug, dw_id_by_slug.get(season.slug))
        for season in seasons_to_scan
    ]
    if not dry_run:
        s.rollback()

    # Normal incremental scans only need records newer than the latest settled
    # local episode. A first index or vacated-identifier recovery still uses the
    # complete snapshot because it intentionally needs historical records.
    full_history_scan = (
        initial_index
        or latest_final_episode_slug is None
        or bool(vacated_identifiers)
    )
    prefetched: dict[int, list[DwEpisodeRecord]] = {}
    for season_id, _season_slug, remote_id in season_requests:
        if remote_id is None:
            continue

        if (
            not full_history_scan
            and season_id == latest_final_season_id
            and latest_final_episode_slug is not None
        ):
            prefetched[season_id] = fetch_episodes_until_slug(
                client,
                collection_slug,
                ByShowSeason(
                    season_dw_id=remote_id,
                    membership_plan=membership_plan,
                    page_size=50,
                    order_by="CreatedAt_DESC",
                ),
                stop_slug=latest_final_episode_slug,
            )
            continue

        prefetched[season_id] = fetch_all_episodes_paginated(
            client,
            collection_slug,
            ByShowSeason(
                season_dw_id=remote_id,
                membership_plan=membership_plan,
                page_size=50,
                order_by="CreatedAt_ASC",
            ),
        )

    if not dry_run:
        collection = s.get(Collection, collection_id)
        if collection is None:
            raise ValueError(f"Collection {collection_id} was removed while it was being indexed")
        latest_final_episode = (
            s.get(Episode, latest_final_episode_id)
            if latest_final_episode_id is not None
            else None
        )

    for season_id, records in prefetched.items():
        season = get_season_from_list_by_id(collection.seasons, season_id)
        if season is None:
            continue
        if reconcile_single_pending_episode_slug(
            s,
            collection=collection,
            season=season,
            remote_records=records,
        ) is not None:
            # Refresh requests with the newly adopted slug while keeping immutable id identity.
            for episode in s.scalars(select(Episode).where(
                Episode.collection_id == collection_id,
                Episode.publish_status.in_(PENDING_EPISODE_PUBLISH_STATUSES),
            )):
                monitor_requests[episode.id] = _monitor_request_for_db_episode(collection, episode)

    candidate_remote_slugs = {
        record.slug
        for records in prefetched.values()
        for record in records
    }
    known_episode_slugs = (
        set(s.scalars(
            select(Episode.slug).where(
                Episode.collection_id == collection_id,
                Episode.slug.in_(candidate_remote_slugs),
            )
        ))
        if candidate_remote_slugs
        else set()
    )
    occupied_identifiers = set(
        s.scalars(select(Episode.episode_identifier).where(Episode.collection_id == collection_id))
    )
    prev_max_values: IdentifierMaxValues = {
        item.key: int(item.value)
        for item in collection.meta_items
        if item.key in {
            "ep_id.latest_aux_num",
            "ep_id.latest_trailer_num",
            "ep_id.latest_ep_date",
        }
    }
    season_count = max(1, min(len(collection.seasons), 5))
    upper = int(65 + (season_count - 1) * (95 - 65) / 4) if season_count > 1 else 65

    ep_map_asc, identifier_max_values = get_dw_episodes_since_ep(
        client,
        collection=collection,
        membership_plan=membership_plan,
        seasons=collection.seasons,
        dw_id_by_slug=dw_id_by_slug,
        since_episode=latest_final_episode,
        prev_max_values=prev_max_values,
        known_episode_slugs=known_episode_slugs,
        progress=progress,
        progress_bounds=ProgressBounds(1, upper),
        order=RecordOrder.ASC,
        prefetched_by_season=prefetched,
        vacated_identifiers=vacated_identifiers,
        occupied_identifiers=occupied_identifiers,
    )

    if dry_run:
        _print_dry_run_report(collection, ep_map_asc, identifier_max_values)
        s.rollback()
        update_progress(progress, 100, f"Dry run complete for '{collection_slug}' (nothing saved)")
        return 0

    total = count_total_episodes(ep_map_asc)
    if total == 0:
        for key, value in identifier_max_values.items():
            collection.set_meta(key=key, value=str(value))
        _queue_monitor_requests(s, monitor_requests.values())
        _queue_collection_indexed(s, collection=collection, indexed_count=0)
        s.commit()
        update_progress(progress, 100, _completion_message(0, len(monitor_requests)))
        return 0

    # Slug reconciliation is now complete. Persist it before resolving individual
    # episode details, then perform all remaining remote/HLS work with no DB
    # connection checked out.
    s.commit()
    always_resolve_details = latest_final_episode_id is not None
    resolved_by_season: dict[int, list[ResolvedEpisode]] = {}
    for season_id, ep_list in ep_map_asc.items():
        resolved_by_season[season_id] = resolve_dw_episodes(
            episodes=ep_list,
            client=client,
            require_member_exclusive=require_member_exclusive,
            always_resolve_details=always_resolve_details,
        )

    collection = s.get(Collection, collection_id)
    if collection is None:
        raise ValueError(f"Collection {collection_id} was removed while it was being indexed")
    resolved_by_season, identifier_max_values = _canonicalize_resolved_identifiers(
        collection=collection,
        resolved_by_season=resolved_by_season,
        previous_values=prev_max_values,
        occupied_identifiers=occupied_identifiers,
    )
    for key, value in identifier_max_values.items():
        collection.set_meta(key=key, value=str(value))

    latest_episode_index = get_latest_ep_index(s, collection=collection) or 0
    current_index = latest_episode_index + 1
    for season_id, resolved_episodes in resolved_by_season.items():
        season = get_season_from_list_by_id(collection.seasons, season_id)
        if season is None:
            continue
        current_index, saved_episodes = save_resolved_episodes_per_season_asc(
            s,
            collection=collection,
            season=season,
            episodes=resolved_episodes,
            start_index=current_index,
        )
        _announce_new_episodes(
            s,
            collection=collection,
            saved_episodes=saved_episodes,
            monitor_requests=monitor_requests,
        )

    _queue_monitor_requests(s, monitor_requests.values())
    from backend.services.custom_indexes import request_collection_custom_index_reconciliation
    request_collection_custom_index_reconciliation(s, collection.id)
    _queue_collection_indexed(s, collection=collection, indexed_count=total)
    s.commit()
    update_progress(progress, 100, _completion_message(total, len(monitor_requests)))
    return total


def _index_listed_collection(s: Session, *, collection: Collection, source: Source, dry_run: bool, progress=None) -> CollectionEpisodeScanResult:
    result = CollectionEpisodeScanResult(collection_id=collection.id, collection_slug=collection.slug, collection_title=collection.title, episodes_found=0)
    from backend.services.custom_indexes import request_collection_custom_index_reconciliation
    collection_id = collection.id
    newest = newest_media_item_id(s)
    try:
        found = index_listed_collection(s, collection_id=collection_id, source=source, progress=progress, dry_run=dry_run)
        if dry_run:
            update_progress(progress, 100, f"Dry run complete for '{result.collection_slug}': {found} new episodes (nothing saved)")
            return result
        collection = s.get(Collection, collection_id)
        if collection is not None:
            request_collection_custom_index_reconciliation(s, collection_id)
            _queue_collection_indexed(s, collection=collection, indexed_count=found)
        s.commit()
    except Exception:
        s.rollback()
        raise
    if found:
        take_first_frames(s, _episodes_after(s, collection_id, newest))
    return replace(result, episodes_found=found)


def _episodes_after(s: Session, collection_id: int, newest: int) -> list[int]:
    """The collection's episodes added after the media item ``newest``."""
    return list(s.scalars(select(Episode.id).where(Episode.collection_id == collection_id, Episode.id > newest)))


def _announce_new_episodes(
    s: Session,
    *,
    collection: Collection,
    saved_episodes: list[SavedEpisode],
    monitor_requests: dict[int, dict],
) -> None:
    for saved in saved_episodes:
        if not saved.detail_resolved:
            continue
        queue_episode_status_events(
            s,
            episode=saved.episode,
            collection=collection,
            old_status=None,
            new_status=saved.status,
            was_created=True,
        )
        if saved.status.value in PENDING_EPISODE_PUBLISH_STATUSES:
            monitor_requests[saved.episode.id] = _monitor_request_for_db_episode(collection, saved.episode)


def _monitor_request_for_db_episode(collection: Collection, episode: Episode) -> dict:
    return {
        "resource_id": episode.id,
        "slug": episode.slug,
        "collection_id": collection.id,
        "collection_slug": collection.slug,
        "season_id": episode.season_id,
        "episode_identifier": episode.episode_identifier,
        "episode_index": episode.index,
        "status": episode.publish_status,
    }


def _queue_monitor_requests(s: Session, requests) -> None:
    for request in requests:
        queue_event(s, MONITOR_REQUESTED_EVENT, request)


def _queue_collection_indexed(s: Session, *, collection: Collection, indexed_count: int) -> None:
    from backend.services.notifications.emitters import new_episodes_found
    new_episodes_found(s, collection, indexed_count)
    queue_event(s, COLLECTION_INDEXED_EVENT, {
        "resource_id": collection.id,
        "id": collection.id,
        "slug": collection.slug,
        "indexed_count": indexed_count,
    })
    # A folder of existing files, or an import's files, waited for these episodes before they could be matched.
    from backend.services.existing_files import start_waiting_scans
    from backend.services.imports import start_waiting_import_steps

    start_waiting_scans(s, collection)
    start_waiting_import_steps(s, collection)


def _completion_message(indexed_count: int, monitor_count: int) -> str:
    if monitor_count:
        return f"Indexed {indexed_count} episode(s); ensured {monitor_count} pending episode monitor(s)"
    return f"Indexed {indexed_count} episode(s); no pending episodes found"


def _print_dry_run_report(collection: Collection, ep_map_asc, identifier_max_values: IdentifierMaxValues) -> None:
    total = count_total_episodes(ep_map_asc)
    print(f"\n=== DRY RUN: '{collection.slug}' — {total} new episode(s), nothing saved ===")
    for season_id, ep_list in ep_map_asc.items():
        season = get_season_from_list_by_id(collection.seasons, season_id)
        season_label = f"season {season.index}: {season.name}" if season is not None else f"season id {season_id}"
        for ep_id, ep in ep_list:
            print(f"  [{season_label}] {ep_id:<32} {ep.title}")
    print("Resulting identifier_max_values:")
    for key, value in sorted(identifier_max_values.items()):
        print(f"  {key} = {value}")
