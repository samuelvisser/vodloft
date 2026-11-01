from fastapi import APIRouter, status

from .service import *
from .as_view import download_profile_view_router
from ...models.download_profile import *
from backend.app import db_session
from backend.security.access import Area, Level
from backend.security.deps import requires, requires_any

router = APIRouter(prefix="/download-profiles", tags=["Download Profiles"])

# Mount sub-routers
router.include_router(download_profile_view_router)


@router.get("", dependencies=[requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[DownloadProfileAPIRead])
def download_profiles_list():
    """
    List all download profiles.
    """
    with db_session() as s:
        return get_download_profiles_list(s)


@router.get("/by-collection-slug/{collection_slug}", dependencies=[requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[DownloadProfileAPIRead])
def download_profiles_by_collection_slug_list(collection_slug: str):
    """
    List all download profiles in any collection.
    """
    with db_session() as s:
        return get_download_profiles_list(s, collection_slug)


@router.get("/{download_profile_id}", dependencies=[requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=DownloadProfileAPIRead)
def download_profile_detail(download_profile_id: int):
    """
    Retrieve a single download profile.
    """
    with db_session() as s:
        return get_download_profile(s, download_profile_id)


@router.post("", dependencies=[requires(Area.DOWNLOAD_PROFILES, Level.MANAGE)], response_model=DownloadProfileAPIRead, status_code=status.HTTP_201_CREATED)
def download_profiles_create(body: DownloadProfileAPICreate):
    """
    Create a new download profile.

    Creates a profile defining which episodes of a collection to download automatically.
    Returns the created profile with tracking information.
    """
    with db_session() as s:
        try:
            result = create_download_profile(s, body)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.patch("/{download_profile_id}", dependencies=[requires(Area.DOWNLOAD_PROFILES, Level.MANAGE)], response_model=DownloadProfileAPIRead)
def download_profiles_update(download_profile_id: int, body: DownloadProfileAPIUpdate):
    """
    Update an existing download profile.
    """
    with db_session() as s:
        try:
            result = update_download_profile(s, download_profile_id, body)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.delete("/{download_profile_id}", dependencies=[requires(Area.DOWNLOAD_PROFILES, Level.MANAGE)], response_model=DownloadProfileAPIRead)
def download_profiles_delete(download_profile_id: int):
    """
    Delete a download profile.

    Permanently removes the specified profile configuration.
    Returns the deleted profile's information for confirmation.
    """
    with db_session() as s:
        try:
            result = delete_download_profile(s, download_profile_id)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise
