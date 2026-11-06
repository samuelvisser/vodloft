from fastapi import APIRouter, status

from backend.api.models.movie_local_media_profile import (
    MovieLocalMediaProfileAPICreate,
    MovieLocalMediaProfileAPIRead,
    MovieLocalMediaProfileAPIUpdate,
)
from backend.app import db_session

from .service import (
    create_movie_local_media_profile,
    delete_movie_local_media_profile,
    get_movie_local_media_profile,
    get_movie_local_media_profiles_list,
    update_movie_local_media_profile,
)
from backend.security.access import Area, Level
from backend.security.deps import requires, requires_any
from backend.db.core import run_write_transaction


router = APIRouter(
    prefix="/movie-local-media-profiles",
    tags=["Media Profiles (movie)"],
)


@router.get("", dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[MovieLocalMediaProfileAPIRead])
def movie_local_media_profiles_list():
    with db_session() as s:
        return get_movie_local_media_profiles_list(s)


@router.post(
    "",
    dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)],
    response_model=MovieLocalMediaProfileAPIRead,
    status_code=status.HTTP_201_CREATED,
)
def movie_local_media_profiles_create(body: MovieLocalMediaProfileAPICreate):
    def work(s):
        return create_movie_local_media_profile(s, body)

    return run_write_transaction(work)


@router.get(
    "/{local_media_profile_slug}",
    dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))],
    response_model=MovieLocalMediaProfileAPIRead,
)
def movie_local_media_profiles_detail(local_media_profile_slug: str):
    with db_session() as s:
        return get_movie_local_media_profile(s, local_media_profile_slug)


@router.patch(
    "/{local_media_profile_slug}",
    dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)],
    response_model=MovieLocalMediaProfileAPIRead,
)
def movie_local_media_profiles_update(
    local_media_profile_slug: str,
    body: MovieLocalMediaProfileAPIUpdate,
):
    def work(s):
        result = update_movie_local_media_profile(
            s,
            local_media_profile_slug,
            body,
        )
        return result

    return run_write_transaction(work)


@router.delete(
    "/{local_media_profile_slug}",
    dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)],
    response_model=MovieLocalMediaProfileAPIRead,
)
def movie_local_media_profiles_delete(local_media_profile_slug: str):
    def work(s):
        return delete_movie_local_media_profile(s, local_media_profile_slug)

    return run_write_transaction(work)
