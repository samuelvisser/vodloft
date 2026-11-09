from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.models.collection import CollectionAPIReadView
from backend.db.models import Episode, Collection


@dataclass(frozen=True)
class _CollectionViewSource:
    collection: Collection
    episode_count: int
    years: str
    first_published_date: Optional[datetime]


def _episode_stats():
    return (
        select(
            Episode.collection_id.label("collection_id"),
            func.count(Episode.id).label("episode_count"),
            func.min(Episode.published_date).label("min_published_date"),
            func.max(Episode.published_date).label("max_published_date"),
        )
        .group_by(Episode.collection_id)
        .subquery()
    )


def _collection_view_statement():
    stats = _episode_stats()
    return (
        select(
            Collection,
            func.coalesce(stats.c.episode_count, 0),
            stats.c.min_published_date,
            stats.c.max_published_date,
        )
        .outerjoin(stats, stats.c.collection_id == Collection.id)
    )


def _to_view(
    collection: Collection,
    episode_count: int,
    min_published_date,
    max_published_date,
) -> CollectionAPIReadView:
    years = (
        f"{min_published_date.year}-{max_published_date.year}"
        if min_published_date and max_published_date
        else ""
    )
    return CollectionAPIReadView.model_validate(_CollectionViewSource(
        collection=collection,
        episode_count=int(episode_count or 0),
        years=years,
        first_published_date=min_published_date,
    ))


def get_collection_views_list(s: Session) -> list[CollectionAPIReadView]:
    rows = s.execute(_collection_view_statement().order_by(Collection.title.asc())).all()
    return [_to_view(*row) for row in rows]


def get_collection_view(s: Session, collection_slug: str) -> CollectionAPIReadView:
    collection: Optional[Collection] = s.query(Collection).filter_by(slug=collection_slug).one_or_none()
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    episode_count, min_published_date, max_published_date = s.execute(
        select(
            func.count(Episode.id),
            func.min(Episode.published_date),
            func.max(Episode.published_date),
        ).where(Episode.collection_id == collection.id)
    ).one()
    return _to_view(
        collection,
        episode_count,
        min_published_date,
        max_published_date,
    )
