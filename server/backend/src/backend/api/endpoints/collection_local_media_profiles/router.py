from fastapi import APIRouter, status

from backend.api.models.operations import LocalMediaProfileFileRenameOperationAccepted
from backend.api.models.collection_local_media_profile import (
    CollectionLocalMediaProfileAPICreate,
    CollectionLocalMediaProfileAPIRead,
    CollectionLocalMediaProfileAPIUpdate,
)
from backend.app import db_session
from backend.services.profile_file_renames import (
    request_collection_local_media_profile_file_rename,
)

from .service import (
    create_collection_local_media_profile,
    delete_collection_local_media_profile,
    get_collection_local_media_profile,
    get_collection_local_media_profiles_list,
    update_collection_local_media_profile,
)
from backend.security.access import Area, Level
from backend.security.deps import requires, requires_any
from backend.db.core import run_write_transaction


router = APIRouter(
    prefix="/collection-local-media-profiles",
    tags=["Media Profiles (show)"],
)


@router.get("", dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[CollectionLocalMediaProfileAPIRead])
def collection_local_media_profiles_list():
    with db_session() as s:
        return get_collection_local_media_profiles_list(s)


@router.post(
    "",
    dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)],
    response_model=CollectionLocalMediaProfileAPIRead,
    status_code=status.HTTP_201_CREATED,
)
def collection_local_media_profiles_create(body: CollectionLocalMediaProfileAPICreate):
    def work(s):
        return create_collection_local_media_profile(s, body)

    return run_write_transaction(work)


@router.post(
    "/{local_media_profile_slug}/rename-files",
    dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)],
    response_model=LocalMediaProfileFileRenameOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_local_media_profile_rename_files(local_media_profile_slug: str):
    def work(s):
        return request_collection_local_media_profile_file_rename(s, local_media_profile_slug)

    return run_write_transaction(work)


@router.get(
    "/{local_media_profile_slug}",
    dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))],
    response_model=CollectionLocalMediaProfileAPIRead,
)
def collection_local_media_profiles_detail(local_media_profile_slug: str):
    with db_session() as s:
        return get_collection_local_media_profile(s, local_media_profile_slug)


@router.patch(
    "/{local_media_profile_slug}",
    dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)],
    response_model=CollectionLocalMediaProfileAPIRead,
)
def collection_local_media_profiles_update(
    local_media_profile_slug: str,
    body: CollectionLocalMediaProfileAPIUpdate,
    rename_files: bool = False,
):
    def work(s):
        result = update_collection_local_media_profile(
            s,
            local_media_profile_slug,
            body,
            rename_files=rename_files,
        )
        return result

    return run_write_transaction(work)


@router.delete(
    "/{local_media_profile_slug}",
    dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)],
    response_model=CollectionLocalMediaProfileAPIRead,
)
def collection_local_media_profiles_delete(local_media_profile_slug: str):
    def work(s):
        return delete_collection_local_media_profile(s, local_media_profile_slug)

    return run_write_transaction(work)
