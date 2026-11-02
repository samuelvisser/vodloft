from backend.db.models import Season, Collection
from backend.services.seasons import create_season_record
from sources.dailywire.api.records import DwSeasonRecord
from sqlalchemy.orm import Session


def create_season_by_dw_season(
    s: Session,
    *,
    collection: Collection,
    dw_season: DwSeasonRecord,
) -> Season:
    last_index = collection.seasons[0].index if collection.seasons else 0
    next_index = last_index + 1
    return create_season_record(
        s,
        collection_id=collection.id,
        index=next_index,
        slug=dw_season.slug,
        name=dw_season.name,
        update_collection_profiles=True,
    )
