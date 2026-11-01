from fastapi import APIRouter

from .service import *
from ....models.stream_profile import StreamProfileAPIReadView
from backend.app import db_session
from backend.security.access import Access, Area, Level
from backend.security.deps import requires_any, signed_in

router = APIRouter(prefix="/as-view")


@router.get("", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[StreamProfileAPIReadView])
def stream_profile_view_list(access: Access = signed_in()):
    """
    List all stream profiles with extended view information.

    Returns a collection of all stream profiles with their base fields plus the show title.
    This is a denormalized view optimized for display.
    """
    with db_session() as s:
        return get_stream_profile_views_list(s, access)


@router.get("/{stream_profile_id}", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=StreamProfileAPIReadView)
def stream_profile_view_detail(stream_profile_id: int, access: Access = signed_in()):
    """
    Retrieve extended view information for a specific stream profile.

    Returns base fields plus related show title and concrete implementation payload.
    """
    with db_session() as s:
        return get_stream_profile_view(s, access, stream_profile_id)
