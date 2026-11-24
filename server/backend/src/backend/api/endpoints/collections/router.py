from fastapi import APIRouter, HTTPException, Query, status

from .as_bundle import collection_as_bundle_router
from .as_view import collection_view_router
from .existing_files.router import router as existing_files_router
from .seasons.router import router as collection_seasons_router
from .health import router as collection_health_router
from .sync_log import collection_scans
from .bulk import change_collections, delete_collections, summarize_collections, sync_collections
from backend.api.endpoints.creators.service import (
    CollectionNotFoundError, LookupPlan, add_collection_to_creator, collection_creator_match, collection_link,
    join_collection_creator, leave_collection_creator, look_up_collection_creator,
)
from backend.api.models.creator import CollectionCreatorJoinAPIIn
from .service import (
    get_collections_list,
    create_collection,
    create_links_only_collection,
    get_collection,
    get_collection_episode_tags,
    update_collection,
    delete_collection,
    request_collection_sync,
    request_collection_metadata_refresh,
    request_collection_download_all,
    request_collection_file_rename,
    request_collection_download_delete,
    request_collection_episode_redownload,
    collection_check_suggestion,
    count_collection_locked,
    check_collection_locked,
    record_collection_opened,
    preview_collection_identification,
    change_collection_identification,
    request_collection_metadata_rewrite,
)
from ...models.operations import (
    CollectionDeleteDownloadsOperationAccepted,
    CollectionDownloadAllOperationAccepted,
    CollectionFileRenameOperationAccepted,
    CollectionMetadataRewriteOperationAccepted,
    CollectionMetadataOperationAccepted,
    CollectionRedownloadOperationAccepted,
    TaskOperationAccepted,
)
from ...models.collection import (
    CollectionAPIRead,
    CollectionAPICreate,
    CollectionAPIUpdate,
    CollectionLinksOnlyAPICreate,
    CollectionCheckSuggestionAPIRead,
    CollectionLockedAPIRead,
    CollectionSyncLogAPIRead,
    CollectionDeleteDownloadsAPIRequest,
    CollectionDownloadAllAPIRequest,
    CollectionFileRenameAPIRequest,
    CollectionIdentificationChangeAPIRequest,
    CollectionIdentificationPreviewAPIRead,
    CollectionMetadataRewriteAPIRequest,
    CollectionRedownloadEpisodesAPIRequest,
)
from ...models.source import EpisodeTagAPIRead
from ...models.collection import CollectionBulkChangesIn
from ...models.profile_bulk import BulkChangeIn, BulkResultRead, BulkSelectionIn, BulkSummaryRead
from backend.api.endpoints.creators import lookups as creator_lookups
from backend.api.endpoints.reconcile import collection_scope, move, preview_move
from backend.api.models.reconcile import MovePreviewAPIRead, ReconcileAPIIn, ReconcileAPIRead
from backend.api.steps import STEPS_RESPONSE, plan_lines, stream_steps
from backend.app import db_session
from backend.types.collection_types import EpisodeIdentifier
from backend.security.access import Access, Area, Level
from backend.security.deps import may_delete_files, requires, signed_in
from backend.db.core import run_write_transaction

router = APIRouter(prefix="/collections", tags=["Collections"])

router.include_router(collection_health_router)
router.include_router(collection_view_router)
router.include_router(collection_as_bundle_router)
router.include_router(existing_files_router)
router.include_router(collection_seasons_router)

@router.get("", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=list[CollectionAPIRead])
def collection_list():
    """
    List all shows in the system.

    Returns a collection of all show records with their basic metadata.
    """
    with db_session() as s:
        return get_collections_list(s)


@router.post("/bulk/summary", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=BulkSummaryRead)
def collections_bulk_summary(body: BulkSelectionIn):
    """What the chosen Collections are set to now, for the Library's bulk edit."""
    with db_session() as s:
        return summarize_collections(s, body)


@router.post("/bulk/change", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=BulkResultRead)
def collections_bulk_change(body: BulkChangeIn[CollectionBulkChangesIn]):
    """Give the chosen Collections the same settings; a setting a Collection's Site doesn't have is left alone."""
    return run_write_transaction(lambda s: change_collections(s, body))


@router.post("/bulk/sync", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=BulkResultRead)
def collections_bulk_sync(body: BulkSelectionIn):
    """Look for new episodes of the chosen Collections now."""
    return run_write_transaction(lambda s: sync_collections(s, body))


@router.post("/bulk/delete", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=BulkResultRead)
def collections_bulk_delete(body: BulkSelectionIn):
    """Delete the chosen Collections, as deleting each on its Edit page does."""
    return run_write_transaction(lambda s: delete_collections(s, body))


@router.post("", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=CollectionAPIRead, status_code=status.HTTP_201_CREATED)
def collection_create(body: CollectionAPICreate, access: Access = signed_in()) -> CollectionAPIRead:
    """
    Create a new show entry.

    Adds a new show to the system with the provided metadata.
    Returns the created show with a generated slug identifier.
    """
    access.check_link_at(body.source_key, body.sharing_url)
    def work(s):
        result = create_collection(s, body, added_by_id=access.user_id)

        return result

    return run_write_transaction(work)


@router.post(
    "/links-only", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=CollectionAPIRead,
    status_code=status.HTTP_201_CREATED,
)
def collection_links_only_create(body: CollectionLinksOnlyAPICreate, access: Access = signed_in()) -> CollectionAPIRead:
    """Create an empty collection without a link of its own, which holds only what the links added to it have."""
    return run_write_transaction(
        lambda s: create_links_only_collection(s, body, added_by_id=access.user_id),
    )


@router.post(
    "/{collection_slug}/sync",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=TaskOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_sync(collection_slug: str):
    """Queue an immediate new-episode sync for one show."""
    def work(s):
        return request_collection_sync(s, collection_slug)

    return run_write_transaction(work)


@router.post(
    "/{collection_slug}/refresh-metadata",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CollectionMetadataOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_metadata_refresh(collection_slug: str):
    """Queue metadata refreshes for every episode in one show."""
    def work(s):
        return request_collection_metadata_refresh(s, collection_slug)

    return run_write_transaction(work)


@router.post(
    "/{collection_slug}/download-all",
    dependencies=[requires(Area.MANAGED_DOWNLOADS, Level.MANAGE)],
    response_model=CollectionDownloadAllOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_download_all(collection_slug: str, body: CollectionDownloadAllAPIRequest):
    """Queue all eligible indexed episodes for one Local Media Profile."""
    def work(s):
        return request_collection_download_all(s, collection_slug, body)

    return run_write_transaction(work)


@router.post(
    "/{collection_slug}/rename-files",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CollectionFileRenameOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_rename_files(collection_slug: str, body: CollectionFileRenameAPIRequest):
    """Rename existing show files for one or every Local Media Profile in use."""
    def work(s):
        result = request_collection_file_rename(
            s,
            collection_slug,
            body.local_media_profile_id,
            season_folders=body.season_folders,
        )
        return result

    return run_write_transaction(work)


@router.post(
    "/{collection_slug}/reconcile/preview", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=MovePreviewAPIRead,
)
def collection_reconcile_preview(collection_slug: str):
    """What moving the collection's Moved episodes to the seasons they belong in now does. Changes nothing."""
    return run_write_transaction(lambda s: preview_move(s, collection_scope(collection_slug)))


@router.post(
    "/{collection_slug}/reconcile", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=ReconcileAPIRead,
)
def collection_reconcile(collection_slug: str, body: ReconcileAPIIn):
    """Move the collection's Moved episodes, with their files, to the seasons they belong in now."""
    return run_write_transaction(lambda s: move(s, collection_scope(collection_slug), body))


@router.post(
    "/{collection_slug}/rewrite-metadata",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CollectionMetadataRewriteOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_rewrite_metadata(collection_slug: str, body: CollectionMetadataRewriteAPIRequest):
    """Rewrite the tags and NFO files of the collection's downloaded files, without downloading them again."""
    return run_write_transaction(
        lambda s: request_collection_metadata_rewrite(s, collection_slug, body.local_media_profile_id)
    )


@router.get(
    "/{collection_slug}/episode-identification",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CollectionIdentificationPreviewAPIRead,
)
def collection_identification_preview(
        collection_slug: str,
        episode_identifier: EpisodeIdentifier = Query(alias="episodeIdentifier"),
):
    """What numbering the collection's episodes another way would do, before it is done."""
    with db_session() as s:
        return preview_collection_identification(s, collection_slug, episode_identifier)


@router.put(
    "/{collection_slug}/episode-identification",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=TaskOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_change_identification(collection_slug: str, body: CollectionIdentificationChangeAPIRequest):
    """Number the collection's episodes another way, then rename its files and rewrite their metadata."""
    return run_write_transaction(lambda s: change_collection_identification(s, collection_slug, body))


@router.post(
    "/{collection_slug}/delete-downloads",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE), may_delete_files()],
    response_model=CollectionDeleteDownloadsOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_delete_downloads(collection_slug: str, body: CollectionDeleteDownloadsAPIRequest):
    """Delete show downloads for one or every Local Media Profile in use."""
    def work(s):
        result = request_collection_download_delete(
            s,
            collection_slug,
            body.local_media_profile_id,
            delete_older_than=body.delete_older_than,
            delete_older_than_days=body.delete_older_than_days,
            delete_older_than_latest_downloads=body.delete_older_than_latest_downloads,
        )
        return result

    return run_write_transaction(work)


@router.post(
    "/{collection_slug}/redownload-episodes",
    dependencies=[requires(Area.MANAGED_DOWNLOADS, Level.MANAGE)],
    response_model=CollectionRedownloadOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_redownload_episodes(collection_slug: str, body: CollectionRedownloadEpisodesAPIRequest):
    """Delete and re-download existing show files for one or every Local Media Profile in use."""
    def work(s):
        result = request_collection_episode_redownload(
            s,
            collection_slug,
            body.local_media_profile_id,
            delete_older_than=body.delete_older_than,
            delete_older_than_days=body.delete_older_than_days,
            delete_older_than_latest_downloads=body.delete_older_than_latest_downloads,
        )
        return result

    return run_write_transaction(work)


@router.get(
    "/{collection_slug}/locked",
    dependencies=[requires(Area.LIBRARY, Level.VIEW)],
    response_model=CollectionLockedAPIRead,
)
def collection_locked(collection_slug: str):
    """How many episodes the Source refused for lack of an access, such as a membership."""
    with db_session() as s:
        return count_collection_locked(s, collection_slug)


@router.post(
    "/{collection_slug}/locked/check",
    dependencies=[requires(Area.MANAGED_DOWNLOADS, Level.MANAGE)],
    response_model=CollectionLockedAPIRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def collection_locked_check(collection_slug: str):
    """Check the locked episodes again now, as after gaining access, and download those the Source gives."""
    return run_write_transaction(lambda s: check_collection_locked(s, collection_slug))


@router.post(
    "/{collection_slug}/opened",
    dependencies=[requires(Area.LIBRARY, Level.VIEW)],
    status_code=status.HTTP_204_NO_CONTENT,
)
def collection_opened(collection_slug: str) -> None:
    """Count that someone opened the Collection's page, so the Library can list the most used Collections first."""
    run_write_transaction(lambda s: record_collection_opened(s, collection_slug), concurrent=True)


@router.get("/{collection_slug}", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=CollectionAPIRead)
def collection_detail(collection_slug: str):
    """
    Retrieve detailed information for a specific show.

    Returns complete show metadata including title, description, and configuration.
    """
    with db_session() as s:
        return get_collection(s, collection_slug)


@router.get("/{collection_slug}/episode-tags", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=list[EpisodeTagAPIRead])
def collection_episode_tags(collection_slug: str):
    """The episode tags, such as Video, Short and Livestream, that the collection's episodes have."""
    with db_session() as s:
        return get_collection_episode_tags(s, collection_slug)


@router.get(
    "/{collection_slug}/check-suggestion",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CollectionCheckSuggestionAPIRead,
)
def collection_check_suggestion_detail(collection_slug: str):
    """How often to check the Collection, from how often it posted lately."""
    with db_session() as s:
        return CollectionCheckSuggestionAPIRead(suggestion=collection_check_suggestion(s, collection_slug))


@router.get(
    "/{collection_slug}/sync-log",
    dependencies=[requires(Area.LIBRARY, Level.VIEW)],
    response_model=CollectionSyncLogAPIRead,
)
def collection_sync_log(
    collection_slug: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
):
    """The scans that looked at this Collection for new episodes, newest first."""
    with db_session() as s:
        scans, total = collection_scans(s, collection_slug, offset=offset, limit=limit)
        return CollectionSyncLogAPIRead(items=scans, total=total)


@router.patch("/{collection_slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=CollectionAPIRead)
def collection_update(collection_slug: str, body: CollectionAPIUpdate):
    """
    Update an existing show's metadata.

    Partially updates show information with the provided fields.
    Only specified fields remain unchanged.
    """
    def work(s):
        return update_collection(s, collection_slug, body)

    return run_write_transaction(work)


@router.delete("/{collection_slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=CollectionAPIRead)
def collection_delete(collection_slug: str):
    """
    Delete a show from the system.

    Permanently removes the specified show and its associated data.
    Returns the deleted show's information for confirmation.
    """
    def work(s):
        return delete_collection(s, collection_slug)

    return run_write_transaction(work)


def _collection_found(work):
    try:
        return work()
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/{collection_slug}/creator/match", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], responses=STEPS_RESPONSE,
)
def collection_creator_match_get(collection_slug: str):
    """Find the creator behind the channel collection's link, and whether they are in the Library already.

    Asking the Site takes a while, so the answer is sent as it goes, a line of JSON each: ``{"plan": ...}`` each time
    the plan of looking the creator up changes, then ``{"match": CollectionCreatorMatchAPIRead}`` or
    ``{"error": "..."}``.
    """
    with db_session() as s:
        link = _collection_found(lambda: collection_link(s, collection_slug))

    def match(send) -> dict:
        plan = LookupPlan(plan_lines(send))
        details = look_up_collection_creator(link, plan)
        with db_session() as s, plan.step("check_library", "Checking what is in your library already"):
            found = collection_creator_match(s, link.source_key, details)
        found.lookup_id = creator_lookups.keep(("collection", collection_slug, link.source_key, link.url), details)
        return {"match": found.model_dump(mode="json", by_alias=True)}

    return stream_steps(match, "Could not look up the creator")


@router.post(
    "/{collection_slug}/creator",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CollectionAPIRead,
)
def collection_creator_join(
    collection_slug: str, body: CollectionCreatorJoinAPIIn | None = None, access: Access = signed_in(),
):
    """Group the channel collection under the creator behind its link, adding the creator when they are not in the
    Library, or with ``creator_slug`` under that creator in the Library. Nothing the collection holds changes."""
    if body is not None and body.creator_slug:
        creator_slug = body.creator_slug
        return _collection_found(lambda: run_write_transaction(
            lambda s: add_collection_to_creator(s, collection_slug, creator_slug)
        ))
    with db_session() as s:
        link = _collection_found(lambda: collection_link(s, collection_slug))
    details = creator_lookups.found(
        body.lookup_id if body is not None else None, ("collection", collection_slug, link.source_key, link.url),
    ) or look_up_collection_creator(link)
    return _collection_found(lambda: run_write_transaction(
        lambda s: join_collection_creator(s, collection_slug, link.source_key, details, added_by_id=access.user_id)
    ))


@router.delete(
    "/{collection_slug}/creator",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=CollectionAPIRead,
)
def collection_creator_remove(collection_slug: str):
    """Take the collection out of its creator. Nothing it holds changes."""
    return _collection_found(lambda: run_write_transaction(lambda s: leave_collection_creator(s, collection_slug)))
