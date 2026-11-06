from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from backend.api.models.custom_metadata import CustomMetadataAPIUpdate
from backend.api.models.movie import MovieAPIRead
from backend.api.models.collection import CollectionAPIRead
from backend.app import db_session
from backend.db.models import Collection
from backend.db.models.media_item import Movie
from backend.services.custom_indexes import request_collection_custom_index_reconciliation
from backend.utils.custom_metadata import (
    CustomMetadataScope,
    replace_custom_metadata,
)


from backend.db.core import run_write_transaction
from .service import (
    get_custom_metadata_fields,
    remove_shared_custom_metadata_fields,
)
from backend.security.access import Area, Level
from backend.security.deps import requires


router = APIRouter(tags=["Custom Metadata"])



@router.get("/custom-metadata/fields", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=list[str])
def custom_metadata_fields(
    scope: CustomMetadataScope = Query(...),
) -> list[str]:
    """List shared custom metadata field names for one media scope."""
    with db_session() as session:
        return get_custom_metadata_fields(session, scope)


@router.put("/collections/{collection_slug}/metadata", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=CollectionAPIRead)
def collection_custom_metadata_update(collection_slug: str, body: CustomMetadataAPIUpdate) -> CollectionAPIRead:
    def work(session):
        collection = session.query(Collection).filter_by(slug=collection_slug).one_or_none()
        if collection is None:
            raise HTTPException(status_code=404, detail="Collection not found")
        remove_shared_custom_metadata_fields(
            session,
            collection,
            parent_table=Collection.__tablename__,
            fields=body.removed_fields,
        )
        replace_custom_metadata(collection, body.custom_metadata)
        request_collection_custom_index_reconciliation(session, collection.id)
        session.flush()
        return CollectionAPIRead.model_validate(collection)

    return run_write_transaction(work)


@router.put("/movies/{movie_slug}/metadata", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=MovieAPIRead)
def movie_custom_metadata_update(movie_slug: str, body: CustomMetadataAPIUpdate) -> MovieAPIRead:
    def work(session):
        movie = session.query(Movie).filter_by(slug=movie_slug).one_or_none()
        if movie is None:
            raise HTTPException(status_code=404, detail="Movie not found")
        remove_shared_custom_metadata_fields(
            session,
            movie,
            parent_table=Movie.__tablename__,
            fields=body.removed_fields,
        )
        replace_custom_metadata(movie, body.custom_metadata)
        session.flush()
        return MovieAPIRead.model_validate(movie)

    return run_write_transaction(work)
