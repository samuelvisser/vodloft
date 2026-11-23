from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, with_expression
from fastapi import HTTPException

from backend.db.model_mapping import update_database_fields
from backend.api.models.season import *
from backend.db.models import Collection, Episode, Season
from backend.services.link_seasons import holds_whole_channel


def get_seasons_list(s: Session, collection_slug: str) -> list[SeasonAPIRead]:
    # Its newest episode tells which season a collection page opens on.
    newest = select(func.max(Episode.published_date)).where(Episode.season_id == Season.id).scalar_subquery()
    seasons = (
        s.query(Season)
        .options(with_expression(Season.newest_published_at, newest))
        .filter(
            Season.collection.has(slug=collection_slug)
        )
        .order_by(Season.id)
        .all()
    )
    collection = s.scalar(select(Collection).where(Collection.slug == collection_slug))
    whole = collection is not None and holds_whole_channel(collection)
    return [
        SeasonAPIRead.model_validate(season).model_copy(update={"whole_channel": whole and season.loose})
        for season in seasons
    ]


def get_season(s: Session, collection_slug: str, season_slug: str) -> SeasonAPIRead:
    season = (
        s.query(Season)
        .filter(
            Season.slug == season_slug,
            Season.collection.has(slug=collection_slug)
        )
        .one_or_none()
    )
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found")

    return SeasonAPIRead.model_validate(season)


def create_season(
    s: Session,
    body: SeasonAPICreate,
    *,
    update_collection_profiles: bool = False,
) -> SeasonAPIRead:
    from backend.services.seasons import create_season_record

    season = create_season_record(
        s,
        collection_id=body.collection_id,
        index=body.index,
        slug=body.slug,
        name=body.name,
        update_collection_profiles=update_collection_profiles,
    )
    return SeasonAPIRead.model_validate(season)



def update_season(s: Session, collection_slug: str, season_slug: str, body: SeasonAPIUpdate) -> SeasonAPIRead:
    season: Optional[Season] = (
        s.query(Season)
        .filter(
            Season.slug == season_slug,
            Season.collection.has(slug=collection_slug)
        )
        .one_or_none()
    )
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found")

    # Apply updates and flush; commit in router
    update_database_fields(season, body)
    s.flush()
    return SeasonAPIRead.model_validate(season)

