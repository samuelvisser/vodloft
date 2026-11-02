from __future__ import annotations
from backend.security.access import Access
from backend.services.stream_profile_owners import check_owner, owned_by

from dataclasses import dataclass
from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload, with_polymorphic
from sqlalchemy.orm.util import AliasedClass

from backend.api.models.stream_profile import StreamProfileAPIReadView
from backend.db.models import RssStreamProfile, Collection, StreamProfileBase


@dataclass(frozen=True)
class _StreamProfileViewSource:
    profile: AliasedClass[StreamProfileBase]


def _to_view(item: AliasedClass[StreamProfileBase]) -> StreamProfileAPIReadView:
    return StreamProfileAPIReadView.model_validate(
        _StreamProfileViewSource(profile=item)
    )


def get_stream_profile_views_list(s: Session, access: Access) -> list[StreamProfileAPIReadView]:
    profile = with_polymorphic(StreamProfileBase, [RssStreamProfile])
    items = (
        owned_by(s.query(profile), profile.owner_user_id, access)
        .options(joinedload(profile.collection))
        .join(Collection, Collection.id == profile.collection_id)
        .order_by(Collection.title.asc(), profile.id.asc())
        .all()
    )
    return [_to_view(item) for item in items]


def get_stream_profile_view(
    s: Session,
    access: Access,
    stream_profile_id: int,
) -> StreamProfileAPIReadView:
    profile = with_polymorphic(StreamProfileBase, [RssStreamProfile])
    item = (
        s.query(profile)
        .options(joinedload(profile.collection))
        .filter_by(id=stream_profile_id)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Stream profile not found")
    check_owner(item, access)
    return _to_view(item)
