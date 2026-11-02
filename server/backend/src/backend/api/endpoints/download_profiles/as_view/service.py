from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload, selectinload

from backend.api.models.download_profile_view import DownloadProfileAPIReadView
from backend.db.models import (
    DownloadProfile,
    LocalMediaProfileBase,
    Collection,
)


@dataclass(frozen=True)
class _DownloadProfileViewSource:
    profile: DownloadProfile


def _to_view(item: DownloadProfile) -> DownloadProfileAPIReadView:
    return DownloadProfileAPIReadView.model_validate(
        _DownloadProfileViewSource(profile=item)
    )


def get_download_profile_views_list(s: Session) -> list[DownloadProfileAPIReadView]:
    items = (
        s.query(DownloadProfile)
        .options(
            joinedload(DownloadProfile.collection),
            joinedload(DownloadProfile.local_media_profile),
            selectinload(DownloadProfile.seasons),
        )
        .join(Collection, Collection.id == DownloadProfile.collection_id)
        .join(
            LocalMediaProfileBase,
            LocalMediaProfileBase.id == DownloadProfile.local_media_profile_id,
        )
        .order_by(Collection.title.asc(), DownloadProfile.id.asc())
        .all()
    )
    return [_to_view(item) for item in items]


def get_download_profile_view(
    s: Session,
    download_profile_id: int,
) -> DownloadProfileAPIReadView:
    item = (
        s.query(DownloadProfile)
        .options(
            joinedload(DownloadProfile.collection),
            joinedload(DownloadProfile.local_media_profile),
            selectinload(DownloadProfile.seasons),
        )
        .filter_by(id=download_profile_id)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Download profile not found")
    return _to_view(item)
