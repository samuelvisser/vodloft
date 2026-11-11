from __future__ import annotations
from backend.security.access import Access
from backend.services.stream_profile_owners import check_owner, owned_by

from dataclasses import dataclass
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, contains_eager, joinedload, with_polymorphic
from sqlalchemy.orm.util import AliasedClass

from backend.api.list_filters import matches_any, matches_format, matches_status, matches_words, scope_of, search_words
from backend.api.models.profile_bulk import ProfileIdsRead
from backend.api.models.profile_list import StreamProfileListQuery, StreamsFrom
from backend.api.models.source import SiteAPIRead
from backend.api.models.stream_profile import StreamProfileAPIReadView, StreamProfileViewPageRead
from backend.api.pagination import InvalidCursorError, SortKey, keyset_page
from backend.db.models import RssStreamProfile, Collection, Site, StreamProfileBase


@dataclass(frozen=True)
class _StreamProfileViewSource:
    profile: AliasedClass[StreamProfileBase]


def _to_view(item: AliasedClass[StreamProfileBase]) -> StreamProfileAPIReadView:
    return StreamProfileAPIReadView.model_validate(
        _StreamProfileViewSource(profile=item)
    )


def _filtered(s: Session, access: Access, filters: StreamProfileListQuery):
    """The Stream Profiles the user may see that the filters match, and the alias to sort them by."""
    profile = with_polymorphic(StreamProfileBase, [RssStreamProfile])
    streams_from = {
        StreamsFrom.DOWNLOADS: profile.use_downloads.is_(True),
        StreamsFrom.SOURCE: profile.use_source_stream.is_(True),
    }
    query = (
        owned_by(s.query(profile), profile.owner_user_id, access)
        .join(Collection, Collection.id == profile.collection_id)
        .filter(
            matches_words(
                search_words(filters.search),
                func.coalesce(profile.overwrite_collection_title, Collection.title),
                Collection.title,
            ),
            matches_any([Collection.site_key.in_(filters.site)] if filters.site else []),
            matches_status(profile.enable_profile, filters.status),
            matches_any([streams_from[value] for value in set(filters.streams_from)]),
            matches_format(profile.preferred_format, filters.format),
        )
    )
    return query, profile


def get_stream_profile_views_page(
    s: Session,
    access: Access,
    filters: StreamProfileListQuery,
) -> StreamProfileViewPageRead:
    """One page of the Stream Profiles table, in collection title order."""
    query, profile = _filtered(s, access, filters)
    total = s.scalar(select(func.count()).select_from(query.with_entities(profile.id).subquery()))
    try:
        items, next_cursor = keyset_page(
            query.options(contains_eager(profile.collection)),
            [SortKey(func.lower(Collection.title)), SortKey(profile.id)],
            cursor=filters.cursor, limit=filters.limit, kind="stream-profiles", scope=scope_of(filters),
        )
    except InvalidCursorError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StreamProfileViewPageRead(
        items=[_to_view(item) for item in items], limit=filters.limit, next_cursor=next_cursor, total=int(total or 0),
    )


def get_stream_profile_ids(s: Session, access: Access, filters: StreamProfileListQuery) -> ProfileIdsRead:
    """Every Stream Profile the filters match, for Select all in bulk edit."""
    query, profile = _filtered(s, access, filters)
    rows = query.with_entities(profile.id).order_by(func.lower(Collection.title), profile.id)
    return ProfileIdsRead(ids=[row.id for row in rows])


def get_stream_profile_views_by_collection(
    s: Session,
    access: Access,
    collection_slug: str,
) -> list[StreamProfileAPIReadView]:
    """Every Stream Profile of one Collection the user may see."""
    profile = with_polymorphic(StreamProfileBase, [RssStreamProfile])
    items = (
        owned_by(s.query(profile), profile.owner_user_id, access)
        .join(Collection, Collection.id == profile.collection_id)
        .filter(Collection.slug == collection_slug)
        .options(contains_eager(profile.collection))
        .order_by(profile.id.asc())
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


def get_stream_profile_sites(s: Session, access: Access) -> list[SiteAPIRead]:
    """The Sites of the collections with a Stream Profile the user may see, for the table's Site filter."""
    profiles = owned_by(select(StreamProfileBase.collection_id), StreamProfileBase.owner_user_id, access)
    sites = s.scalars(
        select(Site)
        .where(Site.key.in_(select(Collection.site_key).where(Collection.id.in_(profiles))))
        .order_by(func.lower(Site.name))
    )
    return [SiteAPIRead.model_validate(site) for site in sites]
