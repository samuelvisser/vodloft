from fastapi import APIRouter, Request, status

from .service import *
from ...models.rss_stream_profile import *
from backend.app import db_session
from backend.security.access import Area, Level
from backend.security.deps import requires, requires_any

router = APIRouter(prefix="/rss-stream-profiles", tags=["Stream Profiles (rss)"])


@router.get("", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[RssStreamProfileAPIRead])
def rss_stream_profiles_list():
    """
    List all RSS stream profiles in the system.

    Returns a collection of all RSS stream profile configurations.
    """
    with db_session() as s:
        return get_rss_stream_profiles_list(s)


@router.post("", dependencies=[requires(Area.STREAM_PROFILES, Level.MANAGE)], response_model=RssStreamProfileAPIRead, status_code=status.HTTP_201_CREATED)
def rss_stream_profiles_create(body: RssStreamProfileAPICreate, request: Request):
    """
    Create a new RSS stream profile.

    Creates a profile defining how RSS streams should be handled for a show.
    Returns the created profile with tracking information. If no feed_url is
    given, one is generated automatically.
    """
    with db_session() as s:
        try:
            result = create_stream_profile_rss(s, request, body)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.get("/{rss_stream_profile_id}", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=RssStreamProfileAPIRead)
def rss_stream_profiles_detail(rss_stream_profile_id: int):
    """
    Retrieve detailed information for a specific RSS stream profile.

    Returns complete configuration including show association and profile settings.
    """
    with db_session() as s:
        return get_stream_profile_rss(s, rss_stream_profile_id)


@router.patch("/{rss_stream_profile_id}", dependencies=[requires(Area.STREAM_PROFILES, Level.MANAGE)], response_model=RssStreamProfileAPIRead)
def rss_stream_profiles_update(rss_stream_profile_id: int, body: RssStreamProfileAPIUpdate):
    """
    Update an existing RSS stream profile.

    Partially updates profile configuration with the provided fields.
    Only specified fields will be modified; omitted fields remain unchanged.
    """
    with db_session() as s:
        try:
            result = update_stream_profile_rss(s, rss_stream_profile_id, body)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.post("/{rss_stream_profile_id}/regenerate-token", dependencies=[requires(Area.STREAM_PROFILES, Level.MANAGE)], response_model=RssStreamProfileAPIRead)
def rss_stream_profiles_regenerate_token(rss_stream_profile_id: int, request: Request):
    """
    Rotate the secret token backing this profile's feed and media URLs.

    Immediately invalidates the previous feed URL (e.g. if it leaked).
    """
    with db_session() as s:
        try:
            result = regenerate_stream_profile_rss_token(s, request, rss_stream_profile_id)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.delete("/{rss_stream_profile_id}", dependencies=[requires(Area.STREAM_PROFILES, Level.MANAGE)], response_model=RssStreamProfileAPIRead)
def rss_stream_profiles_delete(rss_stream_profile_id: int):
    """
    Delete an RSS stream profile from the system.

    Permanently removes the specified profile configuration.
    Returns the deleted profile's information for confirmation.
    """
    with db_session() as s:
        try:
            result = delete_stream_profile_rss(s, rss_stream_profile_id)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise
