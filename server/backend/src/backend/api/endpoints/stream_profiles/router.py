from fastapi import APIRouter

from .service import *
from .as_view import stream_profile_view_router
from ...models.stream_profile import *
from backend.app import db_session
from backend.security.access import Access, Area, Level
from backend.security.deps import requires_any, signed_in

router = APIRouter(prefix="/stream-profiles", tags=["Stream Profiles (base)"])

# Mount sub-routers
router.include_router(stream_profile_view_router)


@router.get("", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[StreamProfileAPIRead])
def stream_profiles_list(access: Access = signed_in()):
    """
    List all stream profiles (any type).
    """
    with db_session() as s:
        return get_stream_profiles_list(s, access)


@router.get("/by-collection-slug/{collection_slug}", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[StreamProfileAPIRead])
def stream_profiles_by_collection_slug_list(collection_slug: str, access: Access = signed_in()):
    """
    List all download profiles in any collection.
    """
    with db_session() as s:
        return get_stream_profiles_list(s, access, collection_slug)

@router.get("/{stream_profile_id}", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=StreamProfileAPIRead)
def stream_profile_detail(stream_profile_id: int, access: Access = signed_in()):
    """
    Retrieve a single stream profile by its base id.
    """
    with db_session() as s:
        return get_stream_profile(s, access, stream_profile_id)
