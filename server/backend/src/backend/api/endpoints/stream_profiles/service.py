from __future__ import annotations
from backend.security.access import Access
from backend.services.stream_profile_owners import check_owner, owned_by

from typing import Optional

from sqlalchemy.orm import Session, with_polymorphic
from fastapi import HTTPException

from backend.api.models.stream_profile import StreamProfileAPIRead
from backend.api.models.rss_stream_profile import RssStreamProfileAPIRead
from backend.types.stream_profile_types import StreamProfileType
from backend.db.models import StreamProfileBase, RssStreamProfile


def get_stream_profiles_list(s: Session, access: Access, collection_slug: Optional[str] = None) -> list[StreamProfileAPIRead]:
    SP = with_polymorphic(StreamProfileBase, [RssStreamProfile])
    if collection_slug is not None:
        items = (
            owned_by(s.query(SP), SP.owner_user_id, access)
            .filter(
                SP.collection.has(slug=collection_slug)
            )
            .order_by(SP.id.asc())
            .all()
        )
    else:
        items = (
            owned_by(s.query(SP), SP.owner_user_id, access)
            .order_by(SP.id.asc())
            .all()
        )
    return [StreamProfileAPIRead.model_validate(it) for it in items]


def get_stream_profile(s: Session, access: Access, stream_profile_id: int) -> StreamProfileAPIRead:
    SP = with_polymorphic(StreamProfileBase, [RssStreamProfile])
    item: Optional[SP] = (
        s.query(SP)
        .filter_by(id=stream_profile_id)
        .one_or_none()
    )

    if item is None:
        raise HTTPException(status_code=404, detail="Stream profile not found")
    check_owner(item, access)

    return StreamProfileAPIRead.model_validate(item)
