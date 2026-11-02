from fastapi import APIRouter

from .service import *
from ....models.download_profile_view import DownloadProfileAPIReadView
from backend.app import db_session
from backend.security.access import Area, Level
from backend.security.deps import requires_any

router = APIRouter(prefix="/as-view")


@router.get("", dependencies=[requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[DownloadProfileAPIReadView])
def download_profile_view_list():
    """
    List all download profiles with extended view information.

    Returns a collection of all download profiles with their base fields plus the collection title
    and local media profile display fields. This is a denormalized view optimized for display.
    """
    with db_session() as s:
        return get_download_profile_views_list(s)


@router.get("/{download_profile_id}", dependencies=[requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=DownloadProfileAPIReadView)
def download_profile_view_detail(download_profile_id: int):
    """
    Retrieve extended view information for a specific download profile.

    Returns base fields plus the related collection title and local media profile display fields.
    """
    with db_session() as s:
        return get_download_profile_view(s, download_profile_id)
