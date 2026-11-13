from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from backend.api.models.collection_example import ExampleCollectionAPIIn

from backend.api.models.local_media_profile import (
    LocalMediaProfileSitesAPIRead,
    LocalMediaProfileTemplateSource,
    LocalMediaProfileTemplateSourcePage,
    LocalMediaProfileTemplateVariable,
)
from backend.api.models.local_media_profile_view import (
    LocalMediaProfileAPIRead,
    LocalMediaProfileViewAPIRead,
    LocalMediaProfileViewPageRead,
)
from backend.api.models.profile_list import LocalMediaProfileListQuery
from backend.api.models.source import SiteAPIRead
from backend.api.models.local_media_profile_move import (
    LocalMediaProfileMoveAPIRequest,
    LocalMediaProfileMovePreviewAPIRead,
)
from backend.api.models.operations import (
    LocalMediaProfileDeleteDownloadsOperationAccepted,
    LocalMediaProfileFileRenameOperationAccepted,
    LocalMediaProfileMoveEpisodesOperationAccepted,
    LocalMediaProfileRedownloadOperationAccepted,
)
from backend.app import db_session
from backend.services.local_media_profile_sites import profile_sites
from backend.types.local_media_profile_types import (
    LocalMediaProfileType,
    CollectionLocalMediaProfileScope,
)

from .output_template import (
    get_example_template_sources,
    get_output_template_source_page,
    get_random_collection_template_source,
    get_output_template_variables,
)
from backend.services.profile_file_renames import request_local_media_profile_file_rename
from .maintenance import (
    request_local_media_profile_download_delete,
    request_local_media_profile_redownload,
)
from .move import get_move_preview, request_move
from .advisory import router as advisory_router
from .preview import router as preview_router
from .bulk import change_local_media_profiles, delete_local_media_profiles, summarize_local_media_profiles
from backend.api.models.profile_bulk import (
    BulkChangeIn, BulkResultRead, BulkSelectionIn, BulkSummaryRead, LocalMediaProfileBulkChangesIn, ProfileIdsRead,
)
from .service import (
    get_local_media_profile_ids,
    get_local_media_profile_table_sites,
    get_local_media_profile,
    get_local_media_profile_view,
    get_local_media_profile_views_page,
    get_local_media_profiles_list,
)
from backend.security.access import Area, Level
from backend.security import deps
from backend.security.deps import may_delete_files, requires, requires_any
from backend.db.core import run_write_transaction

router = APIRouter(prefix="/local-media-profiles", tags=["Media Profiles (base)"])
router.include_router(preview_router)
router.include_router(advisory_router)


@router.get("", dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[LocalMediaProfileAPIRead])
def local_media_profiles_list():
    """List Local Media Profiles of every type."""
    with db_session() as s:
        return get_local_media_profiles_list(s)


@router.get("/sites", dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=LocalMediaProfileSitesAPIRead)
def local_media_profile_sites():
    """Every Site VODLoft knows that a Local Media Profile can be offered for."""
    with db_session() as s:
        return LocalMediaProfileSitesAPIRead.model_validate(profile_sites(s))


@router.get("/as-view", dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=LocalMediaProfileViewPageRead)
def local_media_profiles_view_list(
        filters: Annotated[LocalMediaProfileListQuery, Query()],
):
    """One page of Local Media Profiles together with management statistics, in name order.

    The filters narrow the list and its total; `nextCursor` continues it.
    """
    with db_session() as s:
        return get_local_media_profile_views_page(s, filters)


@router.get("/as-view/ids", dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=ProfileIdsRead)
def local_media_profiles_view_ids(
        filters: Annotated[LocalMediaProfileListQuery, Query()],
):
    """The ids of every Local Media Profile the filters match, in table order, for Select all."""
    with db_session() as s:
        return get_local_media_profile_ids(s, filters)


@router.get("/as-view/sites", dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[SiteAPIRead])
def local_media_profiles_view_sites():
    """The Sites VODLoft has media from, which the table can be filtered by."""
    with db_session() as s:
        return get_local_media_profile_table_sites(s)


@router.post("/bulk/summary", dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)], response_model=BulkSummaryRead)
def local_media_profiles_bulk_summary(body: BulkSelectionIn):
    """What the chosen profiles are set to now, for the bulk edit's Change settings."""
    with db_session() as s:
        return summarize_local_media_profiles(s, body)


@router.post("/bulk/change", dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)], response_model=BulkResultRead)
def local_media_profiles_bulk_change(body: BulkChangeIn[LocalMediaProfileBulkChangesIn]):
    """Give the chosen profiles the same download, thumbnail, metadata, subtitle and collection image behavior."""
    return run_write_transaction(lambda s: change_local_media_profiles(s, body))


@router.post("/bulk/delete", dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)], response_model=BulkResultRead)
def local_media_profiles_bulk_delete(body: BulkSelectionIn):
    """Delete the chosen profiles; one still in use is skipped."""
    return run_write_transaction(lambda s: delete_local_media_profiles(s, body))


@router.get("/template/variables", dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[LocalMediaProfileTemplateVariable])
def local_media_profile_template_variables(
    type: LocalMediaProfileType = Query(...),
):
    """Return custom variables available to one output-template type."""
    with db_session() as s:
        try:
            return get_output_template_variables(s, type)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


_SITES_HELP = "Comma-separated keys of the Sites the profile is for; left out, every Site"


def _site_keys(sites: str | None) -> list[str] | None:
    return None if sites is None else [key for key in sites.split(",") if key]


@router.get("/template/sources", dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=LocalMediaProfileTemplateSourcePage)
def local_media_profile_template_sources(
    type: LocalMediaProfileType = Query(...),
    collection_scope: CollectionLocalMediaProfileScope = Query(CollectionLocalMediaProfileScope.BOTH),
    search: str | None = Query(None, max_length=200),
    cursor: str | None = Query(None, max_length=4096),
    limit: int = Query(30, ge=1, le=100),
    anchor_source_id: str | None = Query(None, max_length=100),
    sites: str | None = Query(None, max_length=4096, description=_SITES_HELP),
):
    """Search applicable media items for testing an output path template."""
    with db_session() as s:
        try:
            return get_output_template_source_page(
                s,
                type,
                collection_scope,
                search=search,
                cursor=cursor,
                limit=limit,
                anchor_source_id=anchor_source_id,
                site_keys=_site_keys(sites),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/template/sources/random-collection-episode",
    dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))],
    response_model=LocalMediaProfileTemplateSource | None,
)
def local_media_profile_random_collection_template_source(
    collection_scope: CollectionLocalMediaProfileScope = Query(CollectionLocalMediaProfileScope.BOTH),
    local_media_profile_id: int | None = Query(None, description="Prefer a Collection that uses this profile"),
    sites: str | None = Query(None, max_length=4096, description=_SITES_HELP),
):
    """Choose a fresh initial episode without weighting Collections by episode count."""
    with db_session() as s:
        return get_random_collection_template_source(
            s, collection_scope, local_media_profile_id=local_media_profile_id, site_keys=_site_keys(sites),
        )


@router.post(
    "/template/sources/examples",
    dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)],
    response_model=list[LocalMediaProfileTemplateSource],
)
def local_media_profile_example_template_sources(body: ExampleCollectionAPIIn, request: Request):
    """The newest episodes of a collection that is being added, as examples. They are never saved."""
    if not deps.request_access(request).allows_source(body.source_key):
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        return get_example_template_sources(body.example())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not look up the newest episodes: {exc}") from exc


@router.get(
    "/{local_media_profile_slug}/view",
    dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))],
    response_model=LocalMediaProfileViewAPIRead,
)
def local_media_profiles_view(local_media_profile_slug: str):
    """Retrieve one Local Media Profile together with management statistics."""
    with db_session() as s:
        return get_local_media_profile_view(s, local_media_profile_slug)


@router.post(
    "/{local_media_profile_slug}/rename-files",
    dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)],
    response_model=LocalMediaProfileFileRenameOperationAccepted,
    status_code=202,
)
def local_media_profiles_rename_files(local_media_profile_slug: str):
    def work(s):
        result = request_local_media_profile_file_rename(
            s,
            local_media_profile_slug,
        )
        return result

    return run_write_transaction(work)


@router.post(
    "/{local_media_profile_slug}/delete-downloads",
    dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE), may_delete_files()],
    response_model=LocalMediaProfileDeleteDownloadsOperationAccepted,
    status_code=202,
)
def local_media_profiles_delete_downloads(local_media_profile_slug: str):
    def work(s):
        result = request_local_media_profile_download_delete(
            s,
            local_media_profile_slug,
        )
        return result

    return run_write_transaction(work)


@router.post(
    "/{local_media_profile_slug}/redownload-media",
    dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)],
    response_model=LocalMediaProfileRedownloadOperationAccepted,
    status_code=202,
)
def local_media_profiles_redownload_media(local_media_profile_slug: str):
    def work(s):
        result = request_local_media_profile_redownload(
            s,
            local_media_profile_slug,
        )
        return result

    return run_write_transaction(work)


@router.get(
    "/{local_media_profile_slug}/move-episodes/preview",
    dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)],
    response_model=LocalMediaProfileMovePreviewAPIRead,
)
def local_media_profiles_move_episodes_preview(local_media_profile_slug: str, target: str = Query(min_length=1)):
    """What moving this profile's episodes to the target profile would do. Changes nothing."""
    with db_session() as s:
        return get_move_preview(s, local_media_profile_slug, target)


@router.post(
    "/{local_media_profile_slug}/move-episodes",
    dependencies=[requires(Area.LOCAL_MEDIA_PROFILES, Level.MANAGE)],
    response_model=LocalMediaProfileMoveEpisodesOperationAccepted,
    status_code=202,
)
def local_media_profiles_move_episodes(local_media_profile_slug: str, request: LocalMediaProfileMoveAPIRequest):
    def work(s):
        return request_move(s, local_media_profile_slug, request)

    return run_write_transaction(work)


@router.get("/{local_media_profile_slug}", dependencies=[requires_any((Area.LOCAL_MEDIA_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=LocalMediaProfileAPIRead)
def local_media_profiles_detail(local_media_profile_slug: str):
    """Retrieve a Local Media Profile of any type."""
    with db_session() as s:
        return get_local_media_profile(s, local_media_profile_slug)
