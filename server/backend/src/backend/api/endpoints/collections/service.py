from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, or_, select, update

from sqlalchemy.orm import Session

from backend.db.model_mapping import create_database_fields, update_database_fields
from backend.services.check_frequency import check_suggestion
from backend.api.models.collection import *
from backend.api.models.source import EpisodeTagAPIRead
from fastapi import HTTPException

from backend.db.models import Episode, Season, Collection, CollectionLocalMediaProfile
from backend.db.models.media_download import EpisodeMediaDownload
from backend.types.episode_types import EpisodePublishStatus
from backend.services.access_checks import ask_for_check, refused_media
from backend.services.media_access import locked_clause
from backend.services.local_media_profile_sources import profile_offered_for_source
from backend.types.local_media_profile_types import CollectionLocalMediaProfileScope
from backend.types.collection_types import CollectionType
from backend.api.endpoints.media_downloads.service import create_new_episode_download
from config import get_settings
from sources import get_source
from backend.services.custom_indexes import request_collection_custom_index_reconciliation
from backend.services.metadata_refresh import refreshes_metadata
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.utils.episode import episode_identifier_type_predicate
from backend.utils.episode_download_scope import EpisodeDownloadScope
from task_manager.events.transactional import queue_event
from task_manager.scheduler.operation_factory import create_operation
from task_manager.scheduler.operations import (
    complete_operation,
    queue_operation_target_dispatch,
)
from task_manager.tasks.helpers.download_profiles import (
    disable_download_profiles_for_episode_scope,
)
from task_manager.tasks.media_download_operations import attach_redownload_dependencies
from task_manager.scheduler.types import OperationSource

from backend.services.collections import add_collection, index_new_collection
from backend.operations.collections import (
    CollectionDeleteDownloadsOperation,
    CollectionDownloadAllOperation,
    CollectionFileRenameOperation,
    CollectionMetadataRefreshOperation,
    CollectionRedownloadOperation,
    CollectionSyncOperation,
)


_PHYSICAL_ARTIFACT_STATUSES = (
    MediaDownloadArtifactStatus.AVAILABLE.value,
    MediaDownloadArtifactStatus.CORRUPTED.value,
)
_CollectionDownloadMaintenanceOperation = CollectionDeleteDownloadsOperation | CollectionRedownloadOperation


def _select_collection_episode_download_scope(
        s: Session,
        collection: Collection,
        *,
        local_media_profile_id: int | None,
        artifact_statuses: tuple[str, ...] | None = None,
) -> EpisodeDownloadScope:
    """Load the selected scope first; validate only if that selection is empty."""
    scope = EpisodeDownloadScope.resolve(
        s,
        collection_id=collection.id,
        local_media_profile_id=local_media_profile_id,
        artifact_statuses=artifact_statuses,
    )
    if scope.downloads:
        return scope

    collection_has_downloads = exists(
        select(EpisodeMediaDownload.id)
        .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
        .where(Episode.collection_id == collection.id)
    )

    # Without an artifact filter, an empty scope already proves the requested
    # profile is empty. Only the broader collection-level error still needs resolving.
    if artifact_statuses is None:
        if local_media_profile_id is None:
            raise HTTPException(
                status_code=422,
                detail="This collection has no episode downloads",
            )
        if not s.scalar(select(collection_has_downloads)):
            raise HTTPException(
                status_code=422,
                detail="This collection has no episode downloads",
            )
        raise HTTPException(
            status_code=422,
            detail="Local Media Profile has no downloads for this collection",
        )

    # An artifact filter can legitimately produce an empty scope even when the
    # collection/profile has downloads. Resolve those validation facts in one fallback
    # statement instead of loading an unfiltered collection.
    if local_media_profile_id is None:
        if not s.scalar(select(collection_has_downloads)):
            raise HTTPException(
                status_code=422,
                detail="This collection has no episode downloads",
            )
        return scope

    profile_has_downloads = exists(
        select(EpisodeMediaDownload.id)
        .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
        .where(
            Episode.collection_id == collection.id,
            EpisodeMediaDownload.local_media_profile_id
            == local_media_profile_id,
        )
    )
    has_collection_downloads, has_profile_downloads = s.execute(
        select(collection_has_downloads, profile_has_downloads)
    ).one()
    if not has_collection_downloads:
        raise HTTPException(
            status_code=422,
            detail="This collection has no episode downloads",
        )
    if not has_profile_downloads:
        raise HTTPException(
            status_code=422,
            detail="Local Media Profile has no downloads for this collection",
        )
    return scope


def _resolve_collection_download_maintenance_scope(
        s: Session,
        collection_slug: str,
        local_media_profile_id: int | None,
) -> tuple[Collection, EpisodeDownloadScope]:
    collection = (
        s.query(Collection)
        .filter_by(slug=collection_slug)
        .one_or_none()
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    scope = _select_collection_episode_download_scope(
        s,
        collection,
        local_media_profile_id=local_media_profile_id,
    )
    return collection, scope


def _queue_collection_download_maintenance(
        s: Session,
        scope: EpisodeDownloadScope,
        operation: _CollectionDownloadMaintenanceOperation,
) -> dict[str, bool | int | str]:
    queued_operation = create_operation(s, operation)
    queue_operation_target_dispatch(
        s,
        queued_operation.id,
        queued_operation.targets[0].slot_key,
    )
    return {
        "queued": True,
        "local_media_profiles_queued": scope.local_media_profile_count,
        "operation_id": queued_operation.id,
    }


def get_collections_list(s: Session) -> list[CollectionAPIRead]:
    collections = (
        s.query(Collection)
        .order_by(Collection.title.asc())
        .all()
    )
    return [CollectionAPIRead.model_validate(collection) for collection in collections]


def _collection_id(s: Session, collection_slug: str) -> int:
    collection_id = s.scalar(select(Collection.id).where(Collection.slug == collection_slug))
    if collection_id is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection_id


def record_collection_opened(s: Session, collection_slug: str) -> None:
    """Count one more opening of the Collection's page, for the Library's Often used and Recently used orders."""
    opened = s.execute(
        update(Collection)
        .where(Collection.slug == collection_slug)
        # Opening the page does not change the Collection, so it keeps its last update time.
        .values(
            open_count=Collection.open_count + 1,
            last_opened_at=datetime.now(timezone.utc),
            updated_at=Collection.updated_at,
        )
    )
    if opened.rowcount == 0:
        raise HTTPException(status_code=404, detail="Collection not found")


def count_collection_locked(s: Session, collection_slug: str) -> CollectionLockedAPIRead:
    collection_id = _collection_id(s, collection_slug)
    count = s.scalar(select(func.count(Episode.id)).where(
        Episode.collection_id == collection_id, Episode.access.is_not(None), Episode.access_refused_at.is_not(None),
    ))
    return CollectionLockedAPIRead(count=count or 0)


def check_collection_locked(s: Session, collection_slug: str) -> CollectionLockedAPIRead:
    """Check the episodes the Source refused again now, and download those it gives."""
    collection_id = _collection_id(s, collection_slug)
    return CollectionLockedAPIRead(count=ask_for_check(s, refused_media(s, Episode.collection_id == collection_id)))


def get_collection(s: Session, collection_slug: str) -> CollectionAPIRead:
    collection = (
        s.query(Collection)
        .filter_by(slug=collection_slug)
        .one_or_none()
    )

    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    return CollectionAPIRead.model_validate(collection)


def get_collection_episode_tags(s: Session, collection_slug: str) -> list[EpisodeTagAPIRead]:
    """The tags of the collection's Source that at least one of its episodes has, in the Source's order."""
    collection = s.scalar(select(Collection).where(Collection.slug == collection_slug))
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    return [
        EpisodeTagAPIRead.model_validate(tag)
        for tag in get_source(collection.source_key).episode_tags_for(collection.sharing_url)
        if s.scalar(select(exists().where(
            Episode.collection_id == collection.id,
            episode_identifier_type_predicate(Episode.episode_identifier, {tag.key}),
        )))
    ]


def create_collection(s: Session, body: CollectionAPICreate, *, added_by_id: int | None = None) -> CollectionAPIRead:
    collection = create_database_fields(Collection, body)
    add_collection(s, collection, added_by_id=added_by_id)
    index_new_collection(s, collection)

    return CollectionAPIRead.model_validate(collection)


def update_collection(s: Session, collection_slug: str, body: CollectionAPIUpdate) -> CollectionAPIRead:
    collection: Optional[Collection] = (
        s.query(Collection)
        .filter_by(slug=collection_slug)
        .one_or_none()
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    left_out = {
        name for name in ("membership_level", "ytdlp_options", "cookies_mode", "episode_order", "check_frequency", "check_cron")
        if getattr(body, name) is None
    }
    update_database_fields(collection, body, exclude_fields=left_out or None)
    s.flush()
    request_collection_custom_index_reconciliation(s, collection.id)

    queue_event(s, "collection.updated", {
        "resource_id": collection.id,
        "id": collection.id,
        "slug": collection.slug,
    })

    return CollectionAPIRead.model_validate(collection)


def collection_check_suggestion(s: Session, collection_slug: str) -> Optional[str]:
    collection = s.query(Collection).filter_by(slug=collection_slug).one_or_none()
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return check_suggestion(s, collection)


def delete_collection(s: Session, collection_slug: str) -> CollectionAPIRead:
    collection = (
        s.query(Collection)
        .filter_by(slug=collection_slug)
        .one_or_none()
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    payload = CollectionAPIRead.model_validate(collection)

    queue_event(s, "collection.deleted", {
        "resource_id": collection.id,
        "id": collection.id,
        "slug": collection.slug,
    })

    s.delete(collection)
    s.flush()

    return payload


def request_collection_sync(s: Session, collection_slug: str) -> dict[str, bool | str]:
    collection = (
        s.query(Collection)
        .filter_by(slug=collection_slug)
        .one_or_none()
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    operation = create_operation(s, CollectionSyncOperation(collection))
    queue_operation_target_dispatch(s, operation.id, operation.targets[0].slot_key)
    return {"queued": True, "operation_id": operation.id}


def request_collection_metadata_refresh(
        s: Session,
        collection_slug: str,
) -> dict[str, bool | int | str]:
    """Queue the normal metadata refresh flow for every episode in one collection."""
    collection = (
        s.query(Collection)
        .filter_by(slug=collection_slug)
        .one_or_none()
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    if not refreshes_metadata(collection.source_key):
        raise HTTPException(
            status_code=409,
            detail=f"The episodes of {collection.title} are kept up to date by the daily catalogue refresh",
        )

    episodes = (
        s.query(Episode)
        .filter_by(collection_id=collection.id)
        .all()
    )
    operation = create_operation(
        s,
        CollectionMetadataRefreshOperation(collection, episodes),
    )

    if not episodes:
        complete_operation(
            s,
            operation.id,
            summary=f"No episodes to refresh in {collection.title}",
            data={"episodes_refreshed": 0, "episodes_requested": 0},
        )
    else:
        for episode in episodes:
            if queue_operation_target_dispatch(s, operation.id, f"episode:{episode.id}"):
                episode.metadata_is_final = False

    s.flush()
    return {
        "queued": bool(episodes),
        "episodes_queued": len(episodes),
        "operation_id": operation.id,
    }


def request_collection_download_all(
        s: Session,
        collection_slug: str,
        body: CollectionDownloadAllAPIRequest,
) -> dict[str, bool | int | str]:
    """Download indexed, published episodes for one profile without replacing available files."""
    collection = s.scalar(select(Collection).where(Collection.slug == collection_slug))
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    profile = s.get(CollectionLocalMediaProfile, body.local_media_profile_id)
    if profile is None:
        raise HTTPException(status_code=422, detail="Select a Collection Local Media Profile")
    if profile.collection_scope not in (CollectionLocalMediaProfileScope.BOTH, collection.type):
        raise HTTPException(status_code=422, detail="Local Media Profile is not available for this collection type")
    if not profile_offered_for_source(profile.source_keys, collection.source_key):
        raise HTTPException(status_code=422, detail="Local Media Profile is not available for this Source")

    if not body.episode_types:
        raise HTTPException(status_code=422, detail="Select at least one episode type")
    published_at = func.coalesce(Episode.published_date, Episode.went_live_date)
    statement = select(Episode).where(
        Episode.collection_id == collection.id,
        Episode.publish_status.in_((
            EpisodePublishStatus.PUBLISHED_FINAL,
            EpisodePublishStatus.PUBLISHED_PRELIMINARY,
        )),
        episode_identifier_type_predicate(Episode.episode_identifier, set(body.episode_types)),
        # Media protected by DRM, or no longer at the Source, cannot be downloaded.
        Episode.drm_protected.is_(False),
        Episode.removed_from_source.is_(False),
        # Nor can media locked behind an access VODLoft does not have, such as a channel membership.
        ~locked_clause(Episode),
    )
    if collection.type == CollectionType.SERIES.value:
        if not body.season_ids:
            raise HTTPException(status_code=422, detail="Select at least one season")
        if body.download_days_in_past or body.download_episode_count or body.download_starting_from:
            raise HTTPException(status_code=422, detail="Podcast limits cannot be used for series")
        selected_ids = set(body.season_ids)
        valid_ids = set(s.scalars(
            select(Season.id).where(Season.collection_id == collection.id, Season.id.in_(selected_ids))
        ))
        if selected_ids != valid_ids:
            raise HTTPException(status_code=422, detail="A selected season does not belong to this collection")
        statement = (
            statement.where(Episode.season_id.in_(selected_ids))
            .order_by(Episode.season_id.asc(), Episode.index.asc(), Episode.id.asc())
        )
    else:
        if body.season_ids:
            raise HTTPException(status_code=422, detail="Podcast downloads cannot filter by season")
        if body.download_days_in_past:
            cutoff = datetime.now(timezone.utc) - timedelta(days=body.download_days_in_past)
            statement = statement.where(or_(published_at.is_(None), published_at >= cutoff))
        elif body.download_starting_from is not None:
            local_start = datetime.combine(
                body.download_starting_from, time.min,
                tzinfo=ZoneInfo(get_settings().timezone),
            )
            statement = statement.where(
                published_at.is_not(None),
                published_at >= local_start.astimezone(timezone.utc),
            )
        statement = statement.order_by(published_at.desc(), Episode.id.desc())
        if body.download_episode_count:
            statement = statement.limit(body.download_episode_count)

    episodes = list(s.scalars(statement))
    existing_by_episode = {
        download.media_item_id: download
        for download in s.scalars(
            select(EpisodeMediaDownload).where(
                EpisodeMediaDownload.local_media_profile_id == profile.id,
                EpisodeMediaDownload.media_item_id.in_([episode.id for episode in episodes]),
            )
        )
    }
    downloads: list[EpisodeMediaDownload] = []
    for episode in episodes:
        download = existing_by_episode.get(episode.id)
        if download is not None and download.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value:
            continue
        if download is None:
            download = create_new_episode_download(s, episode, profile)
        downloads.append(download)

    operation = create_operation(
        s,
        CollectionDownloadAllOperation(
            collection,
            local_media_profile_id=profile.id,
            download_count=len(downloads),
        ),
    )
    if downloads:
        attach_redownload_dependencies(
            s, operation, tuple(downloads),
            source=OperationSource.SYSTEM.value,
            respect_episode_publication=True,
        )
    else:
        complete_operation(
            s,
            operation.id,
            summary=f"No new episodes to download for {collection.title}",
            data={"downloads_completed": 0},
        )

    s.flush()
    return {
        "queued": bool(downloads),
        "episodes_queued": len(downloads),
        "operation_id": operation.id,
    }


def _select_collection_downloads_older_than(
        s: Session,
        scope: EpisodeDownloadScope,
        *,
        delete_older_than: str,
        delete_older_than_days: int | None,
        delete_older_than_latest_downloads: int | None,
) -> EpisodeDownloadScope:
    """Select older downloads, excluding episodes that have never been downloaded.

    The latest-downloads limit counts actual artifacts in the selected Local Media
    Profile scope. AVAILABLE and CORRUPTED represent existing downloaded files;
    ABSENT or MISSING records cannot consume retention slots. Downloads without
    a usable episode publication date are preserved for filtered deletions.
    """
    if delete_older_than == "all":
        return scope

    published_at = func.coalesce(Episode.published_date, Episode.went_live_date)
    published_episodes = (
        Episode.collection_id == scope.collection.id,
        Episode.publish_status.in_((
            EpisodePublishStatus.PUBLISHED_FINAL,
            EpisodePublishStatus.PUBLISHED_PRELIMINARY,
        )),
        published_at.is_not(None),
    )

    if delete_older_than == "latest_downloads":
        if delete_older_than_latest_downloads is None or delete_older_than_latest_downloads <= 0:
            raise HTTPException(status_code=422, detail="Specify a positive number of latest downloads")

        # Count one slot per existing downloaded artifact, not per indexed episode.
        # Keeping the first N artifacts preserves the newest downloads even when
        # many more recent episodes have never been downloaded.
        older_download_ids = (
            select(EpisodeMediaDownload.id)
            .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
            .where(
                Episode.collection_id == scope.collection.id,
                published_at.is_not(None),
                EpisodeMediaDownload.local_media_profile_id.in_(scope.local_media_profile_ids),
                EpisodeMediaDownload.artifact_status.in_(_PHYSICAL_ARTIFACT_STATUSES),
            )
            .order_by(published_at.desc(), Episode.id.desc(), EpisodeMediaDownload.id.desc())
            .offset(delete_older_than_latest_downloads)
        )
        return scope.select(media_download_ids=set(s.scalars(older_download_ids)))

    if delete_older_than == "days":
        if delete_older_than_days is None or delete_older_than_days <= 0:
            raise HTTPException(status_code=422, detail="Specify a positive number of days")
        cutoff = datetime.now(timezone.utc) - timedelta(days=delete_older_than_days)
        older_episode_ids = select(Episode.id).where(
            *published_episodes,
            published_at < cutoff,
        )
        return scope.select(episode_ids=set(s.scalars(older_episode_ids)))

    raise HTTPException(status_code=422, detail="Invalid Delete older than option")


def request_collection_download_delete(
        s: Session,
        collection_slug: str,
        local_media_profile_id: int | None,
        *,
        delete_older_than: str = "all",
        delete_older_than_days: int | None = None,
        delete_older_than_latest_downloads: int | None = None,
) -> dict[str, bool | int | str]:
    """Queue deletion; deleting everything also disables the affected profiles first."""
    collection, scope = _resolve_collection_download_maintenance_scope(
        s,
        collection_slug,
        local_media_profile_id,
    )
    scope = _select_collection_downloads_older_than(
        s,
        scope,
        delete_older_than=delete_older_than,
        delete_older_than_days=delete_older_than_days,
        delete_older_than_latest_downloads=delete_older_than_latest_downloads,
    )

    # Deleting everything disables the profiles before the operation can be
    # dispatched. The router commits these profile changes and the operation
    # atomically, so no delete worker can observe the profiles still enabled.
    # A partial delete leaves them on: the user may want those episodes
    # downloaded again.
    partial = delete_older_than != "all"
    disabled_profile_count = 0 if partial else disable_download_profiles_for_episode_scope(s, scope)
    result = _queue_collection_download_maintenance(
        s,
        scope,
        CollectionDeleteDownloadsOperation(
            collection,
            local_media_profile_id=local_media_profile_id,
            selected_profile_count=scope.local_media_profile_count,
            disabled_profile_count=disabled_profile_count,
            selected_media_download_ids=(
                tuple(download.id for download in scope.downloads)
                if partial else None
            ),
        ),
    )
    return {
        **result,
        "download_profiles_disabled": disabled_profile_count,
    }


def request_collection_episode_redownload(
        s: Session,
        collection_slug: str,
        local_media_profile_id: int | None,
        *,
        delete_older_than: str = "all",
        delete_older_than_days: int | None = None,
        delete_older_than_latest_downloads: int | None = None,
) -> dict[str, bool | int | str]:
    """Queue replacement downloads for existing collection artifacts in the selected profile scope."""
    collection, scope = _resolve_collection_download_maintenance_scope(
        s,
        collection_slug,
        local_media_profile_id,
    )
    scope = _select_collection_downloads_older_than(
        s,
        scope,
        delete_older_than=delete_older_than,
        delete_older_than_days=delete_older_than_days,
        delete_older_than_latest_downloads=delete_older_than_latest_downloads,
    )
    scope = scope.select(artifact_statuses=(
        MediaDownloadArtifactStatus.AVAILABLE.value,
        MediaDownloadArtifactStatus.MISSING.value,
        MediaDownloadArtifactStatus.CORRUPTED.value,
    ))
    if not scope.downloads:
        raise HTTPException(
            status_code=422,
            detail="This collection has no previously downloaded episode media in the selected scope",
        )
    operation = create_operation(
        s,
        CollectionRedownloadOperation(
            collection,
            local_media_profile_id=local_media_profile_id,
            selected_profile_count=scope.local_media_profile_count,
            download_count=len(scope.downloads),
        ),
    )
    attach_redownload_dependencies(s, operation, tuple(scope.downloads))
    s.flush()
    return {
        "queued": True,
        "local_media_profiles_queued": scope.local_media_profile_count,
        "operation_id": operation.id,
    }


def request_collection_file_rename(
        s: Session,
        collection_slug: str,
        local_media_profile_id: int | None,
) -> dict[str, bool | int | str]:
    """Rename existing collection artifacts using collision-safe profile-wide plans."""
    collection = (
        s.query(Collection)
        .filter_by(slug=collection_slug)
        .one_or_none()
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    rename_scope = _select_collection_episode_download_scope(
        s,
        collection,
        local_media_profile_id=local_media_profile_id,
        artifact_statuses=_PHYSICAL_ARTIFACT_STATUSES,
    )
    profile_ids = rename_scope.local_media_profile_ids

    operation = create_operation(
        s,
        CollectionFileRenameOperation(
            collection,
            local_media_profile_ids=profile_ids,
        ),
    )
    if not profile_ids:
        complete_operation(
            s,
            operation.id,
            summary=f"No existing files to rename in {collection.title}",
            data={
                "files_renamed": 0,
                "files_unchanged": 0,
                "files_recovered": 0,
                "files_considered": 0,
            },
        )
    else:
        for profile_id in profile_ids:
            queue_operation_target_dispatch(s, operation.id, f"profile:{profile_id}")

    s.flush()
    return {
        "queued": bool(profile_ids),
        "episodes_queued": len(rename_scope.episode_ids),
        "local_media_profiles_queued": len(profile_ids),
        "operation_id": operation.id,
    }
