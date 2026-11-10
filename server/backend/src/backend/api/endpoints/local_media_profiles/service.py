from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, with_polymorphic

from backend.api.list_filters import matches_any, matches_format, matches_words, scope_of, search_words
from backend.api.models.local_media_profile_view import (
    LocalMediaProfileAPIRead,
    LocalMediaProfileStatisticsAPIRead,
    LocalMediaProfileViewAPIRead,
    LocalMediaProfileViewPageRead,
)
from backend.api.models.profile_bulk import ProfileIdsRead
from backend.api.models.profile_list import LocalMediaProfileListQuery, StorageUse, UsedFor
from backend.api.pagination import InvalidCursorError, SortKey, keyset_page
from backend.db.models import (
    DownloadProfile,
    LocalMediaProfileBase,
    MediaDownloadBase,
)
from backend.types.local_media_profile_types import CollectionLocalMediaProfileScope, LocalMediaProfileType
from backend.services.storage_used import is_physical_download, storage_size_bytes_sum
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from downloader import hls_asset_marker
from task_manager.tasks.workers.file_watcher.service import resolve_media_download_file


def _raise_profile_in_use(message: str) -> None:
    raise HTTPException(
        status_code=409,
        detail=[{
            "loc": ["body", "__all__"],
            "msg": message,
            "type": "resource_in_use",
        }],
    )


def _path_is_file(path: str | None) -> bool:
    if not path:
        return False
    try:
        return Path(path).is_file()
    except OSError:
        # A path that cannot safely be inspected must never make a destructive
        # profile deletion less restrictive.
        return True


def _download_has_physical_artifact(
    s: Session,
    download: MediaDownloadBase,
) -> bool:
    if download.artifact_status != MediaDownloadArtifactStatus.ABSENT.value:
        if resolve_media_download_file(s, download) is not None:
            return True
    elif _path_is_file(download.file_path):
        # ABSENT is normally paired with an unresolved .ext path or a path whose
        # file has already been removed. Still inspect it so stale state cannot
        # orphan a file during profile deletion.
        return True

    if download.file_path and Path(download.file_path).suffix.lower() == ".m3u8":
        try:
            if hls_asset_marker(Path(download.file_path)).is_file():
                return True
        except OSError:
            return True

    # Auxiliary files are first-class download assets, including NFO metadata
    # and language-specific subtitle sidecars. Never orphan a remaining asset
    # when deleting a profile whose primary media was already removed.
    return any(_path_is_file(asset.path) for asset in download.assets)


def ensure_local_media_profile_can_be_deleted(
    s: Session,
    local_media_profile: LocalMediaProfileBase,
) -> tuple[MediaDownloadBase, ...]:
    has_download_profiles = (
        s.query(DownloadProfile.id)
        .filter(DownloadProfile.local_media_profile_id == local_media_profile.id)
        .first()
        is not None
    )
    if has_download_profiles:
        _raise_profile_in_use(
            "This Local Media Profile cannot be deleted because one or more Download Profiles still use it. "
            "Change or delete those Download Profiles before deleting the profile."
        )

    downloads = tuple(
        s.query(MediaDownloadBase)
        .filter(MediaDownloadBase.local_media_profile_id == local_media_profile.id)
        .order_by(MediaDownloadBase.id)
        .all()
    )
    for download in downloads:
        if _download_has_physical_artifact(s, download):
            _raise_profile_in_use(
                "This Local Media Profile cannot be deleted because one or more managed downloads still have "
                "a physical file. Delete all downloads for this profile first."
            )

    return downloads


_local_media_profile_read_adapter = TypeAdapter(LocalMediaProfileAPIRead)


def _to_read(local_media_profile: LocalMediaProfileBase) -> LocalMediaProfileAPIRead:
    return _local_media_profile_read_adapter.validate_python(
        local_media_profile,
        from_attributes=True,
    )


def _get_local_media_profile_record(
    s: Session,
    local_media_profile_slug: str,
) -> LocalMediaProfileBase:
    profile = with_polymorphic(LocalMediaProfileBase, "*")
    local_media_profile = (
        s.query(profile)
        .filter(profile.slug == local_media_profile_slug)
        .one_or_none()
    )
    if local_media_profile is None:
        raise HTTPException(status_code=404, detail="Media profile not found")
    return local_media_profile


def get_local_media_profiles_list(s: Session) -> list[LocalMediaProfileAPIRead]:
    profile = with_polymorphic(LocalMediaProfileBase, "*")
    items = (
        s.query(profile)
        .order_by(profile.id)
        .all()
    )
    return [_to_read(item) for item in items]


def _get_local_media_profile_statistics(
    s: Session,
    local_media_profile_ids: list[int],
) -> dict[int, LocalMediaProfileStatisticsAPIRead]:
    if not local_media_profile_ids:
        return {}

    download_rows = (
        s.query(
            MediaDownloadBase.local_media_profile_id,
            func.count(MediaDownloadBase.id),
            func.coalesce(
                func.sum(case((is_physical_download(), 1), else_=0)),
                0,
            ),
            storage_size_bytes_sum(),
        )
        .filter(MediaDownloadBase.local_media_profile_id.in_(local_media_profile_ids))
        .group_by(MediaDownloadBase.local_media_profile_id)
        .all()
    )
    download_statistics = {
        int(local_media_profile_id): (
            int(managed_media_count),
            int(downloaded_media_count),
            int(storage_size_bytes),
        )
        for (
            local_media_profile_id,
            managed_media_count,
            downloaded_media_count,
            storage_size_bytes,
        ) in download_rows
    }

    download_profile_counts = {
        int(local_media_profile_id): int(download_profile_count)
        for local_media_profile_id, download_profile_count in (
            s.query(
                DownloadProfile.local_media_profile_id,
                func.count(DownloadProfile.id),
            )
            .filter(DownloadProfile.local_media_profile_id.in_(local_media_profile_ids))
            .group_by(DownloadProfile.local_media_profile_id)
            .all()
        )
    }

    return {
        local_media_profile_id: LocalMediaProfileStatisticsAPIRead(
            managed_media_count=download_statistics.get(local_media_profile_id, (0, 0, 0))[0],
            downloaded_media_count=download_statistics.get(local_media_profile_id, (0, 0, 0))[1],
            storage_size_bytes=download_statistics.get(local_media_profile_id, (0, 0, 0))[2],
            download_profile_count=download_profile_counts.get(local_media_profile_id, 0),
        )
        for local_media_profile_id in local_media_profile_ids
    }


def _views(s: Session, items: list[LocalMediaProfileBase]) -> list[LocalMediaProfileViewAPIRead]:
    statistics_by_profile_id = _get_local_media_profile_statistics(s, [item.id for item in items])
    return [
        LocalMediaProfileViewAPIRead(profile=_to_read(item), statistics=statistics_by_profile_id[item.id])
        for item in items
    ]


def _filtered(s: Session, filters: LocalMediaProfileListQuery):
    """The Local Media Profiles the filters match, and the alias to sort them by."""
    profile = with_polymorphic(LocalMediaProfileBase, "*")
    scope = profile.CollectionLocalMediaProfile.collection_scope
    is_collection = profile.type == LocalMediaProfileType.COLLECTION.value
    used_for = {
        UsedFor.PODCAST: is_collection & scope.in_([
            CollectionLocalMediaProfileScope.PODCAST.value, CollectionLocalMediaProfileScope.BOTH.value,
        ]),
        UsedFor.SERIES: is_collection & scope.in_([
            CollectionLocalMediaProfileScope.SERIES.value, CollectionLocalMediaProfileScope.BOTH.value,
        ]),
        UsedFor.MOVIE: profile.type == LocalMediaProfileType.MOVIE.value,
        UsedFor.VIDEO: profile.type == LocalMediaProfileType.VIDEO.value,
    }
    has_files = (
        select(MediaDownloadBase.id)
        .where(
            MediaDownloadBase.local_media_profile_id == profile.id,
            is_physical_download(),
            MediaDownloadBase.artifact_size_bytes > 0,
        )
        .exists()
    )
    storage = {StorageUse.FILES: has_files, StorageUse.EMPTY: ~has_files}
    # There are only a handful of profiles, and their Sites are a JSON list: pick them here.
    offered_for_site = profile.id.in_([
        profile_id for profile_id, site_keys in s.execute(select(LocalMediaProfileBase.id, LocalMediaProfileBase.site_keys))
        if set(site_keys or ()) & set(filters.site)
    ]) if filters.site else None
    query = s.query(profile).filter(
        matches_words(search_words(filters.search), profile.name, profile.output_template),
        matches_any([used_for[value] for value in set(filters.used_for)]),
        matches_format(profile.preferred_format, filters.format),
        matches_any([storage[value] for value in set(filters.storage)] if set(filters.storage) != set(StorageUse) else []),
        matches_any([offered_for_site] if offered_for_site is not None else []),
    )
    return query, profile


def get_local_media_profile_views_page(
    s: Session,
    filters: LocalMediaProfileListQuery,
) -> LocalMediaProfileViewPageRead:
    """One page of the Local Media Profiles table, in name order."""
    query, profile = _filtered(s, filters)
    total = s.scalar(select(func.count()).select_from(query.with_entities(profile.id).subquery()))
    try:
        items, next_cursor = keyset_page(
            query,
            [SortKey(func.lower(profile.name)), SortKey(profile.id)],
            cursor=filters.cursor, limit=filters.limit, kind="local-media-profiles", scope=scope_of(filters),
        )
    except InvalidCursorError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LocalMediaProfileViewPageRead(
        items=_views(s, items), limit=filters.limit, next_cursor=next_cursor, total=int(total or 0),
    )


def get_local_media_profile(
    s: Session,
    local_media_profile_slug: str,
) -> LocalMediaProfileAPIRead:
    return _to_read(_get_local_media_profile_record(s, local_media_profile_slug))


def get_local_media_profile_view(
    s: Session,
    local_media_profile_slug: str,
) -> LocalMediaProfileViewAPIRead:
    local_media_profile = _get_local_media_profile_record(s, local_media_profile_slug)
    statistics = _get_local_media_profile_statistics(
        s,
        [local_media_profile.id],
    )[local_media_profile.id]

    return LocalMediaProfileViewAPIRead(
        profile=_to_read(local_media_profile),
        statistics=statistics,
    )


def delete_local_media_profile_record(
    s: Session,
    local_media_profile: LocalMediaProfileBase,
) -> None:
    downloads = ensure_local_media_profile_can_be_deleted(s, local_media_profile)
    for download in downloads:
        s.delete(download)
    s.flush()
    s.delete(local_media_profile)
    s.flush()


def get_local_media_profile_ids(s: Session, filters: LocalMediaProfileListQuery) -> ProfileIdsRead:
    """Every Local Media Profile the filters match, for Select all in bulk edit."""
    query, profile = _filtered(s, filters)
    rows = query.with_entities(profile.id).order_by(func.lower(profile.name), profile.id)
    return ProfileIdsRead(ids=[row.id for row in rows])
