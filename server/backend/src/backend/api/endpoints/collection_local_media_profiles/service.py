from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.services import local_media_profile_changes as profile_changes
from backend.api.endpoints.local_media_profiles.service import delete_local_media_profile_record
from backend.api.models.collection_local_media_profile import (
    CollectionLocalMediaProfileAPICreate,
    CollectionLocalMediaProfileAPIRead,
    CollectionLocalMediaProfileAPIUpdate,
)
from backend.db.models import CollectionLocalMediaProfile
from backend.services.custom_indexes import (
    remove_profile_custom_index_state,
)


def get_collection_local_media_profiles_list(
    s: Session,
) -> list[CollectionLocalMediaProfileAPIRead]:
    items = (
        s.query(CollectionLocalMediaProfile)
        .order_by(CollectionLocalMediaProfile.id)
        .all()
    )
    return [CollectionLocalMediaProfileAPIRead.model_validate(item) for item in items]


def get_collection_local_media_profile(
    s: Session,
    local_media_profile_slug: str,
) -> CollectionLocalMediaProfileAPIRead:
    item: Optional[CollectionLocalMediaProfile] = (
        s.query(CollectionLocalMediaProfile)
        .filter_by(slug=local_media_profile_slug)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Collection Local Media Profile not found")
    return CollectionLocalMediaProfileAPIRead.model_validate(item)


def create_collection_local_media_profile(
    s: Session,
    body: CollectionLocalMediaProfileAPICreate,
) -> CollectionLocalMediaProfileAPIRead:
    return CollectionLocalMediaProfileAPIRead.model_validate(profile_changes.create_collection_local_media_profile(s, body))


def update_collection_local_media_profile(
    s: Session,
    local_media_profile_slug: str,
    body: CollectionLocalMediaProfileAPIUpdate,
    *,
    rename_files: bool = False,
) -> CollectionLocalMediaProfileAPIRead:
    return CollectionLocalMediaProfileAPIRead.model_validate(profile_changes.update_collection_local_media_profile(
        s, local_media_profile_slug, body, rename_files=rename_files,
    ))


def delete_collection_local_media_profile(
    s: Session,
    local_media_profile_slug: str,
) -> CollectionLocalMediaProfileAPIRead:
    item: Optional[CollectionLocalMediaProfile] = (
        s.query(CollectionLocalMediaProfile)
        .filter_by(slug=local_media_profile_slug)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Collection Local Media Profile not found")

    payload = CollectionLocalMediaProfileAPIRead.model_validate(item)
    remove_profile_custom_index_state(
        s,
        local_media_profile_id=item.id,
    )
    delete_local_media_profile_record(s, item)
    return payload
