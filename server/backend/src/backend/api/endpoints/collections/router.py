from fastapi import APIRouter, status

from .as_bundle import collection_as_bundle_router
from .as_view import collection_view_router
from .existing_files.router import router as existing_files_router
from .service import (
    get_collections_list,
    create_collection,
    get_collection,
    update_collection,
    delete_collection,
    request_collection_sync,
    request_collection_metadata_refresh,
    request_collection_download_all,
    request_collection_file_rename,
    request_collection_download_delete,
    request_collection_episode_redownload,
)
from ...models.operations import (
    CollectionDeleteDownloadsOperationAccepted,
    CollectionDownloadAllOperationAccepted,
    CollectionFileRenameOperationAccepted,
    CollectionMetadataOperationAccepted,
    CollectionRedownloadOperationAccepted,
    TaskOperationAccepted,
)
from ...models.collection import (
    CollectionAPIRead,
    CollectionAPICreate,
    CollectionAPIUpdate,
    CollectionDeleteDownloadsAPIRequest,
    CollectionDownloadAllAPIRequest,
    CollectionFileRenameAPIRequest,
    CollectionRedownloadEpisodesAPIRequest,
)
from backend.app import db_session
from backend.security.access import Access, Area, Level
from backend.security.deps import may_delete_files, requires, signed_in

router = APIRouter(prefix="/collections", tags=["Collections"])

router.include_router(collection_view_router)
router.include_router(collection_as_bundle_router)
router.include_router(existing_files_router)

@router.get("", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=list[CollectionAPIRead])
def collection_list():
    """
    List all shows in the system.

    Returns a collection of all show records with their basic metadata.
    """
    with db_session() as s:
        return get_collections_list(s)


@router.post("", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=CollectionAPIRead, status_code=status.HTTP_201_CREATED)
def collection_create(body: CollectionAPICreate, access: Access = signed_in()) -> CollectionAPIRead:
    """
    Create a new show entry.

    Adds a new show to the system with the provided metadata.
    Returns the created show with a generated slug identifier.
    """
    access.check_link_at(body.source_key, body.sharing_url)
    with db_session() as s:
        try:
            result = create_collection(s, body)
            s.commit()

            return result
        except Exception:
            s.rollback()
            raise


@router.post(
    "/{collection_slug}/sync",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=TaskOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_sync(collection_slug: str):
    """Queue an immediate new-episode sync for one show."""
    with db_session() as s:
        try:
            result = request_collection_sync(s, collection_slug)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.post(
    "/{collection_slug}/refresh-metadata",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CollectionMetadataOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_metadata_refresh(collection_slug: str):
    """Queue metadata refreshes for every episode in one show."""
    with db_session() as s:
        try:
            result = request_collection_metadata_refresh(s, collection_slug)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.post(
    "/{collection_slug}/download-all",
    dependencies=[requires(Area.MANAGED_DOWNLOADS, Level.MANAGE)],
    response_model=CollectionDownloadAllOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_download_all(collection_slug: str, body: CollectionDownloadAllAPIRequest):
    """Queue all eligible indexed episodes for one Local Media Profile."""
    with db_session() as s:
        try:
            result = request_collection_download_all(s, collection_slug, body)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.post(
    "/{collection_slug}/rename-files",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CollectionFileRenameOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_rename_files(collection_slug: str, body: CollectionFileRenameAPIRequest):
    """Rename existing show files for one or every Local Media Profile in use."""
    with db_session() as s:
        try:
            result = request_collection_file_rename(
                s,
                collection_slug,
                body.local_media_profile_id,
            )
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.post(
    "/{collection_slug}/delete-downloads",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE), may_delete_files()],
    response_model=CollectionDeleteDownloadsOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_delete_downloads(collection_slug: str, body: CollectionDeleteDownloadsAPIRequest):
    """Delete show downloads for one or every Local Media Profile in use."""
    with db_session() as s:
        try:
            result = request_collection_download_delete(
                s,
                collection_slug,
                body.local_media_profile_id,
                delete_older_than=body.delete_older_than,
                delete_older_than_days=body.delete_older_than_days,
                delete_older_than_latest_downloads=body.delete_older_than_latest_downloads,
            )
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.post(
    "/{collection_slug}/redownload-episodes",
    dependencies=[requires(Area.MANAGED_DOWNLOADS, Level.MANAGE)],
    response_model=CollectionRedownloadOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_redownload_episodes(collection_slug: str, body: CollectionRedownloadEpisodesAPIRequest):
    """Delete and re-download existing show files for one or every Local Media Profile in use."""
    with db_session() as s:
        try:
            result = request_collection_episode_redownload(
                s,
                collection_slug,
                body.local_media_profile_id,
                delete_older_than=body.delete_older_than,
                delete_older_than_days=body.delete_older_than_days,
                delete_older_than_latest_downloads=body.delete_older_than_latest_downloads,
            )
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.get("/{collection_slug}", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=CollectionAPIRead)
def collection_detail(collection_slug: str):
    """
    Retrieve detailed information for a specific show.

    Returns complete show metadata including title, description, and configuration.
    """
    with db_session() as s:
        return get_collection(s, collection_slug)


@router.patch("/{collection_slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=CollectionAPIRead)
def collection_update(collection_slug: str, body: CollectionAPIUpdate):
    """
    Update an existing show's metadata.

    Partially updates show information with the provided fields.
    Only specified fields remain unchanged.
    """
    with db_session() as s:
        try:
            result = update_collection(s, collection_slug, body)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.delete("/{collection_slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=CollectionAPIRead)
def collection_delete(collection_slug: str):
    """
    Delete a show from the system.

    Permanently removes the specified show and its associated data.
    Returns the deleted show's information for confirmation.
    """
    with db_session() as s:
        try:
            result = delete_collection(s, collection_slug)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise
