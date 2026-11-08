from typing import Annotated

from fastapi import APIRouter, Query

from .service import *
from ....models.profile_bulk import ProfileIdsRead
from ....models.download_profile_view import DownloadProfileAPIReadView, DownloadProfileViewPageRead
from ....models.profile_list import DownloadProfileListQuery
from backend.app import db_session
from backend.security.access import Area, Level
from backend.security.deps import requires_any

router = APIRouter(prefix="/as-view")

_VIEWERS = [requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))]


@router.get("", dependencies=_VIEWERS, response_model=DownloadProfileViewPageRead)
def download_profile_view_list(
        filters: Annotated[DownloadProfileListQuery, Query()],
):
    """
    One page of download profiles with extended view information, in collection title order.

    Each profile has its base fields plus the collection title and local media profile display fields.
    The filters narrow the list and its total; `nextCursor` continues it.
    """
    with db_session() as s:
        return get_download_profile_views_page(s, filters)


@router.get("/ids", dependencies=_VIEWERS, response_model=ProfileIdsRead)
def download_profile_view_ids(
        filters: Annotated[DownloadProfileListQuery, Query()],
):
    """The ids of every download profile the filters match, in table order, for Select all."""
    with db_session() as s:
        return get_download_profile_ids(s, filters)


@router.get("/by-collection-slug/{collection_slug}", dependencies=_VIEWERS, response_model=list[DownloadProfileAPIReadView])
def download_profile_view_by_collection_list(collection_slug: str):
    """Every download profile of one collection, with extended view information."""
    with db_session() as s:
        return get_download_profile_views_by_collection(s, collection_slug)


@router.get("/{download_profile_id}", dependencies=_VIEWERS, response_model=DownloadProfileAPIReadView)
def download_profile_view_detail(download_profile_id: int):
    """
    Retrieve extended view information for a specific download profile.

    Returns base fields plus the related collection title and local media profile display fields.
    """
    with db_session() as s:
        return get_download_profile_view(s, download_profile_id)
