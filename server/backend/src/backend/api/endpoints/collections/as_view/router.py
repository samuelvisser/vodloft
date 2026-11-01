from fastapi import APIRouter, status

from .service import *
from ....models.collection import *
from backend.app import db_session
from backend.security.access import Area, Level
from backend.security.deps import requires

router = APIRouter(prefix = "/as-view")


@router.get("", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=list[CollectionAPIReadView])
def collection_view_list():
    """
    List all shows with extended view information.

    Returns a collection of all shows with their complete details including seasons, episodes, and profiles.
    This is a denormalized view optimized for display purposes.
    """
    with db_session() as s:
        return get_collection_views_list(s)


@router.get("/{collection_slug}", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=CollectionAPIReadView)
def collection_view_detail(collection_slug: str):
    """
    Retrieve extended view information for a specific show.

    Returns complete show details including all nested relationships such as seasons, episodes, and download profiles.
    This is a denormalized view optimized for display purposes.
    """
    with db_session() as s:
        return get_collection_view(s, collection_slug)