from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Collection, Season, Episode


def get_collections(s: Session, *, collection_id: Optional[int], collection_slug: Optional[str]) -> Sequence[Collection]:
    """Resolve one Collection, or all collections when no collection is given."""
    if collection_slug:
        collection = s.scalar(select(Collection).where(Collection.slug == collection_slug))
        return [collection] if collection is not None else []

    if collection_id is not None:
        collection = s.get(Collection, collection_id)
        return [collection] if collection is not None else []

    return s.scalars(select(Collection)).all()


def get_season_from_list_by_id(season_list: list[Season], season_id: int) -> Optional[Season]:
    for season in season_list:
        if season.id == season_id:
            return season
    return None


def get_latest_ep_index(s: Session, *, collection: Collection) -> Optional[int]:
    return s.execute(select(Episode.index).where(Episode.collection_id == collection.id).order_by(Episode.index.desc()).limit(1)).scalar()
