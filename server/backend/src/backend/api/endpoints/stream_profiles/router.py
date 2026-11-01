from fastapi import APIRouter

from .service import *
from .as_view import stream_profile_view_router
from ...models.stream_profile import *
from backend.app import db_session
from backend.security.access import Area, Level
from backend.security.deps import requires_any

router = APIRouter(prefix="/stream-profiles", tags=["Stream Profiles (base)"])

# Mount sub-routers
router.include_router(stream_profile_view_router)


@router.get("", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[StreamProfileAPIRead])
def stream_profiles_list():
    """
    List all stream profiles (any type).
    """
    with db_session() as s:
        return get_stream_profiles_list(s)


@router.get("/by-show-slug/{show_slug}", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[StreamProfileAPIRead])
def stream_profiles_by_show_slug_list(show_slug: str):
    """
    List all download profiles in any show.
    """
    with db_session() as s:
        return get_stream_profiles_list(s, show_slug)

@router.get("/{stream_profile_id}", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=StreamProfileAPIRead)
def stream_profile_detail(stream_profile_id: int):
    """
    Retrieve a single stream profile by its base id.
    """
    with db_session() as s:
        return get_stream_profile(s, stream_profile_id)
