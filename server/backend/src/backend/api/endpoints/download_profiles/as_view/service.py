from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, contains_eager, joinedload, selectinload

from backend.api.list_filters import matches_any, matches_format, matches_status, matches_words, scope_of, search_words
from backend.api.models.download_profile_view import DownloadProfileAPIReadView, DownloadProfileViewPageRead
from backend.api.models.profile_bulk import ProfileIdsRead
from backend.api.models.profile_list import DownloadProfileListQuery
from backend.api.pagination import InvalidCursorError, SortKey, keyset_page
from backend.db.models import (
    DownloadProfile,
    EpisodeMediaDownload,
    LocalMediaProfileBase,
    Collection,
)
from backend.services.storage_used import storage_size_bytes_sum


@dataclass(frozen=True)
class _DownloadProfileViewSource:
    profile: DownloadProfile
    storage_size_bytes: int


def _storage_size_bytes(s: Session, download_profile_ids: list[int]) -> dict[int, int]:
    """The disk space each Download Profile's downloads take, by profile id."""
    if not download_profile_ids:
        return {}
    rows = (
        s.query(EpisodeMediaDownload.download_profile_id, storage_size_bytes_sum())
        .filter(EpisodeMediaDownload.download_profile_id.in_(download_profile_ids))
        .group_by(EpisodeMediaDownload.download_profile_id)
        .all()
    )
    return {int(profile_id): int(size) for profile_id, size in rows}


def _to_views(s: Session, items: list[DownloadProfile]) -> list[DownloadProfileAPIReadView]:
    storage = _storage_size_bytes(s, [item.id for item in items])
    return [
        DownloadProfileAPIReadView.model_validate(
            _DownloadProfileViewSource(profile=item, storage_size_bytes=storage.get(item.id, 0))
        )
        for item in items
    ]


def _filtered(s: Session, filters: DownloadProfileListQuery):
    words = search_words(filters.search)
    return (
        s.query(DownloadProfile)
        .join(Collection, Collection.id == DownloadProfile.collection_id)
        .join(LocalMediaProfileBase, LocalMediaProfileBase.id == DownloadProfile.local_media_profile_id)
        .filter(
            matches_words(words, Collection.title, LocalMediaProfileBase.name),
            matches_any([Collection.source_key.in_(filters.source)] if filters.source else []),
            matches_status(DownloadProfile.enable_profile, filters.status),
            matches_format(LocalMediaProfileBase.preferred_format, filters.format),
            matches_any(
                [DownloadProfile.local_media_profile_id == filters.local_media_profile_id]
                if filters.local_media_profile_id is not None else []
            ),
        )
    )


def get_download_profile_views_page(
    s: Session,
    filters: DownloadProfileListQuery,
) -> DownloadProfileViewPageRead:
    """One page of the Download Profiles table, in collection title order."""
    query = _filtered(s, filters)
    total = s.scalar(select(func.count()).select_from(query.with_entities(DownloadProfile.id).subquery()))
    try:
        items, next_cursor = keyset_page(
            query.options(
                contains_eager(DownloadProfile.collection),
                contains_eager(DownloadProfile.local_media_profile),
                selectinload(DownloadProfile.filters),
            ),
            [SortKey(func.lower(Collection.title)), SortKey(DownloadProfile.id)],
            cursor=filters.cursor, limit=filters.limit, kind="download-profiles", scope=scope_of(filters),
        )
    except InvalidCursorError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DownloadProfileViewPageRead(
        items=_to_views(s, items), limit=filters.limit, next_cursor=next_cursor, total=int(total or 0),
    )


def get_download_profile_ids(s: Session, filters: DownloadProfileListQuery) -> ProfileIdsRead:
    """Every Download Profile the filters match, for Select all in bulk edit."""
    rows = _filtered(s, filters).with_entities(DownloadProfile.id).order_by(func.lower(Collection.title), DownloadProfile.id)
    return ProfileIdsRead(ids=[row.id for row in rows])


def get_download_profile_views_by_collection(s: Session, collection_slug: str) -> list[DownloadProfileAPIReadView]:
    """Every Download Profile of one Collection, for its page and its stream profiles."""
    items = (
        s.query(DownloadProfile)
        .join(Collection, Collection.id == DownloadProfile.collection_id)
        .filter(Collection.slug == collection_slug)
        .options(
            contains_eager(DownloadProfile.collection),
            joinedload(DownloadProfile.local_media_profile),
            selectinload(DownloadProfile.filters),
        )
        .order_by(DownloadProfile.id.asc())
        .all()
    )
    return _to_views(s, items)


def get_download_profile_view(
    s: Session,
    download_profile_id: int,
) -> DownloadProfileAPIReadView:
    item = (
        s.query(DownloadProfile)
        .options(
            joinedload(DownloadProfile.collection),
            joinedload(DownloadProfile.local_media_profile),
            selectinload(DownloadProfile.filters),
        )
        .filter_by(id=download_profile_id)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Download profile not found")
    return _to_views(s, [item])[0]
