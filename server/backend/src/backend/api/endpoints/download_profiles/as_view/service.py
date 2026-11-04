from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload, selectinload

from backend.api.models.download_profile_view import DownloadProfileAPIReadView
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


def get_download_profile_views_list(s: Session) -> list[DownloadProfileAPIReadView]:
    items = (
        s.query(DownloadProfile)
        .options(
            joinedload(DownloadProfile.collection),
            joinedload(DownloadProfile.local_media_profile),
            selectinload(DownloadProfile.filters),
        )
        .join(Collection, Collection.id == DownloadProfile.collection_id)
        .join(
            LocalMediaProfileBase,
            LocalMediaProfileBase.id == DownloadProfile.local_media_profile_id,
        )
        .order_by(Collection.title.asc(), DownloadProfile.id.asc())
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
