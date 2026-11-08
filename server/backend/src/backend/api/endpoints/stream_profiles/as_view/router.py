from typing import Annotated

from fastapi import APIRouter, Query

from .service import *
from ....models.profile_list import StreamProfileListQuery
from ....models.stream_profile import StreamProfileAPIReadView, StreamProfileViewPageRead
from backend.app import db_session
from backend.security.access import Access, Area, Level
from backend.security.deps import requires_any, signed_in

router = APIRouter(prefix="/as-view")

_VIEWERS = [requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))]


@router.get("", dependencies=_VIEWERS, response_model=StreamProfileViewPageRead)
def stream_profile_view_list(
        filters: Annotated[StreamProfileListQuery, Query()],
        access: Access = signed_in(),
):
    """
    One page of stream profiles with extended view information, in collection title order.

    Each profile has its base fields plus the collection title. The filters narrow the list and its
    total; `nextCursor` continues it.
    """
    with db_session() as s:
        return get_stream_profile_views_page(s, access, filters)


@router.get("/by-collection-slug/{collection_slug}", dependencies=_VIEWERS, response_model=list[StreamProfileAPIReadView])
def stream_profile_view_by_collection_list(collection_slug: str, access: Access = signed_in()):
    """Every stream profile of one collection, with extended view information."""
    with db_session() as s:
        return get_stream_profile_views_by_collection(s, access, collection_slug)


@router.get("/{stream_profile_id}", dependencies=_VIEWERS, response_model=StreamProfileAPIReadView)
def stream_profile_view_detail(stream_profile_id: int, access: Access = signed_in()):
    """
    Retrieve extended view information for a specific stream profile.

    Returns base fields plus related collection title and concrete implementation payload.
    """
    with db_session() as s:
        return get_stream_profile_view(s, access, stream_profile_id)
