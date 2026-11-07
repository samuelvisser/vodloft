from fastapi import APIRouter, Request, status

from .service import *
from ...models.rss_stream_profile import *
from backend.app import db_session
from backend.security.access import Access, Area, Level
from backend.security.deps import requires, requires_any, signed_in
from backend.db.core import run_write_transaction

router = APIRouter(prefix="/rss-stream-profiles", tags=["Stream Profiles (rss)"])


@router.get("", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[RssStreamProfileAPIRead])
def rss_stream_profiles_list(access: Access = signed_in()):
    """
    List all RSS stream profiles in the system.

    Returns a collection of all RSS stream profile configurations.
    """
    with db_session() as s:
        return get_rss_stream_profiles_list(s, access)


@router.post("", dependencies=[requires(Area.STREAM_PROFILES, Level.VIEW)], response_model=RssStreamProfileAPIRead, status_code=status.HTTP_201_CREATED)
def rss_stream_profiles_create(body: RssStreamProfileAPICreate, request: Request, access: Access = signed_in()):
    """
    Create a new RSS stream profile.

    Creates a profile defining how RSS streams should be handled for a collection.
    Returns the created profile with tracking information. If no feed_url is
    given, one is generated automatically.
    """
    def work(s):
        return create_stream_profile_rss(s, request, body, access)

    return run_write_transaction(work)


@router.get("/{rss_stream_profile_id}", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=RssStreamProfileAPIRead)
def rss_stream_profiles_detail(rss_stream_profile_id: int, access: Access = signed_in()):
    """
    Retrieve detailed information for a specific RSS stream profile.

    Returns complete configuration including collection association and profile settings.
    """
    with db_session() as s:
        return get_stream_profile_rss(s, access, rss_stream_profile_id)


@router.patch("/{rss_stream_profile_id}", dependencies=[requires(Area.STREAM_PROFILES, Level.VIEW)], response_model=RssStreamProfileAPIRead)
def rss_stream_profiles_update(rss_stream_profile_id: int, body: RssStreamProfileAPIUpdate, access: Access = signed_in()):
    """
    Update an existing RSS stream profile.

    Partially updates profile configuration with the provided fields.
    Only specified fields will be modified; omitted fields remain unchanged.
    """
    def work(s):
        return update_stream_profile_rss(s, access, rss_stream_profile_id, body)

    return run_write_transaction(work)


@router.post("/{rss_stream_profile_id}/regenerate-token", dependencies=[requires(Area.STREAM_PROFILES, Level.VIEW)], response_model=RssStreamProfileAPIRead)
def rss_stream_profiles_regenerate_token(rss_stream_profile_id: int, request: Request, access: Access = signed_in()):
    """
    Rotate the secret token backing this profile's feed and media URLs.

    Immediately invalidates the previous feed URL (e.g. if it leaked).
    """
    def work(s):
        return regenerate_stream_profile_rss_token(s, access, request, rss_stream_profile_id)

    return run_write_transaction(work)


@router.delete("/{rss_stream_profile_id}", dependencies=[requires(Area.STREAM_PROFILES, Level.VIEW)], response_model=RssStreamProfileAPIRead)
def rss_stream_profiles_delete(rss_stream_profile_id: int, access: Access = signed_in()):
    """
    Delete an RSS stream profile from the system.

    Permanently removes the specified profile configuration.
    Returns the deleted profile's information for confirmation.
    """
    def work(s):
        return delete_stream_profile_rss(s, access, rss_stream_profile_id)

    return run_write_transaction(work)
