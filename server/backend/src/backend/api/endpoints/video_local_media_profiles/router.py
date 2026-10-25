from fastapi import APIRouter, status

from backend.api.models.video_local_media_profile import (
    VideoLocalMediaProfileAPICreate,
    VideoLocalMediaProfileAPIRead,
    VideoLocalMediaProfileAPIUpdate,
)
from backend.app import db_session

from .service import (
    create_video_local_media_profile,
    delete_video_local_media_profile,
    get_video_local_media_profile,
    get_video_local_media_profiles_list,
    update_video_local_media_profile,
)


router = APIRouter(
    prefix="/video-local-media-profiles",
    tags=["Media Profiles (video)"],
)


@router.get("", response_model=list[VideoLocalMediaProfileAPIRead])
def video_local_media_profiles_list():
    with db_session() as s:
        return get_video_local_media_profiles_list(s)


@router.post(
    "",
    response_model=VideoLocalMediaProfileAPIRead,
    status_code=status.HTTP_201_CREATED,
)
def video_local_media_profiles_create(body: VideoLocalMediaProfileAPICreate):
    with db_session() as s:
        try:
            result = create_video_local_media_profile(s, body)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.get(
    "/{local_media_profile_slug}",
    response_model=VideoLocalMediaProfileAPIRead,
)
def video_local_media_profiles_detail(local_media_profile_slug: str):
    with db_session() as s:
        return get_video_local_media_profile(s, local_media_profile_slug)


@router.patch(
    "/{local_media_profile_slug}",
    response_model=VideoLocalMediaProfileAPIRead,
)
def video_local_media_profiles_update(
    local_media_profile_slug: str,
    body: VideoLocalMediaProfileAPIUpdate,
):
    with db_session() as s:
        try:
            result = update_video_local_media_profile(
                s,
                local_media_profile_slug,
                body,
            )
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.delete(
    "/{local_media_profile_slug}",
    response_model=VideoLocalMediaProfileAPIRead,
)
def video_local_media_profiles_delete(local_media_profile_slug: str):
    with db_session() as s:
        try:
            result = delete_video_local_media_profile(s, local_media_profile_slug)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise
