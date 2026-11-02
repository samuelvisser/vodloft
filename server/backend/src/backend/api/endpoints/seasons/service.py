from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session
from fastapi import HTTPException

from backend.db.model_mapping import update_database_fields
from backend.api.models.season import *
from backend.db.models import Season


def get_seasons_list(s: Session, collection_slug: str) -> list[SeasonAPIRead]:
    seasons = (
        s.query(Season)
        .filter(
            Season.collection.has(slug=collection_slug)
        )
        .order_by(Season.id)
        .all()
    )
    return [SeasonAPIRead.model_validate(season) for season in seasons]


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


def delete_season(s: Session, collection_slug: str, season_slug: str) -> SeasonAPIRead:
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

    payload = SeasonAPIRead.model_validate(season)

    queue_event(s, "season.deleted", {
        "resource_id": season.id,
        "id": season.id,
        "slug": season.slug,
        "collection_id": season.collection_id
    })

    s.delete(season)
    s.flush()
    return payload
