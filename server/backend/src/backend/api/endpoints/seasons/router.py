from fastapi import APIRouter, status

from .service import *
from ...models.season import *
from backend.app import db_session
from backend.security.access import Area, Level
from backend.security.deps import requires

router = APIRouter(prefix="/collections/{collection_slug}/seasons", tags=["Seasons"])

@router.get("", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=list[SeasonAPIRead])
def season_list(collection_slug: str):
    """
    List all seasons for a specific collection.

    Returns a collection of all seasons associated with the specified collection slug.
    """
    with db_session() as s:
        return get_seasons_list(s, collection_slug)


@router.post("", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=SeasonAPIRead, status_code=status.HTTP_201_CREATED)
def season_create(body: SeasonAPICreate):
    """
    Create a new season for a collection.

    Creates a new season with the provided metadata and associates it with a collection.
    Returns the created season with a generated slug identifier.
    """
    with db_session() as s:
        try:
            result = create_season(s, body)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.get("/{season_slug}", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=SeasonAPIRead)
def season_detail(collection_slug: str, season_slug: str):
    """
    Retrieve detailed information for a specific season.

    Returns complete season metadata including title, number, and associated episodes.
    """
    with db_session() as s:
        return get_season(s, collection_slug, season_slug)


@router.patch("/{season_slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=SeasonAPIRead)
def season_update(collection_slug: str, season_slug: str, body: SeasonAPIUpdate):
    """
    Update an existing season's metadata.

    Partially updates season information with the provided fields.
    Only specified fields will be modified; omitted fields remain unchanged.
    """
    with db_session() as s:
        try:
            result = update_season(s, collection_slug, season_slug, body)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.delete("/{season_slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=SeasonAPIRead)
def season_delete(collection_slug: str, season_slug: str):
    """
    Delete a season from the system.

    Permanently removes the specified season and its associated data.
    Returns the deleted season's information for confirmation.
    """
    with db_session() as s:
        try:
            result = delete_season(s, collection_slug, season_slug)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise