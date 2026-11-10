from fastapi import APIRouter, HTTPException, Request, status

from .service import *
from .as_view import download_profile_view_router
from .bulk import change_download_profiles, delete_download_profiles, summarize_download_profiles
from ...models.profile_bulk import (
    BulkChangeIn, BulkResultRead, BulkSelectionIn, BulkSummaryRead, DownloadProfileBulkChangesIn,
)
from ...models.download_profile import *
from backend.app import db_session
from backend.services.example_episodes import example_session
from backend.security.access import Area, Level
from backend.security import deps
from backend.security.deps import requires, requires_any
from backend.db.models import Collection
from backend.api.models.source import (
    DownloadOptionsAPIRead, DownloadProfileDefaultsAPIRead, SiteOptionsAPIRead, UpgradeChecksAPIRead,
)
from backend.services.site_settings import download_profile_defaults, offered_settings
from config.settings.site_settings import SiteSettingGroup
from backend.services.sites import collection_site
from backend.db.core import run_write_transaction

router = APIRouter(prefix="/download-profiles", tags=["Download Profiles"])

# Mount sub-routers
router.include_router(download_profile_view_router)


@router.get("", dependencies=[requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[DownloadProfileAPIRead])
def download_profiles_list():
    """
    List all download profiles.
    """
    with db_session() as s:
        return get_download_profiles_list(s)


@router.get("/by-collection-slug/{collection_slug}", dependencies=[requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[DownloadProfileAPIRead])
def download_profiles_by_collection_slug_list(collection_slug: str):
    """
    List all download profiles in any collection.
    """
    with db_session() as s:
        return get_download_profiles_list(s, collection_slug)


@router.post("/bulk/summary", dependencies=[requires(Area.DOWNLOAD_PROFILES, Level.MANAGE)], response_model=BulkSummaryRead)
def download_profiles_bulk_summary(body: BulkSelectionIn):
    """What the chosen profiles are set to now, for the bulk edit's Change settings."""
    with db_session() as s:
        return summarize_download_profiles(s, body)


@router.post("/bulk/change", dependencies=[requires(Area.DOWNLOAD_PROFILES, Level.MANAGE)], response_model=BulkResultRead)
def download_profiles_bulk_change(body: BulkChangeIn[DownloadProfileBulkChangesIn]):
    """Give the chosen profiles the same settings; a setting their Site doesn't have is left alone."""
    return run_write_transaction(lambda s: change_download_profiles(s, body))


@router.post("/bulk/delete", dependencies=[requires(Area.DOWNLOAD_PROFILES, Level.MANAGE)], response_model=BulkResultRead)
def download_profiles_bulk_delete(body: BulkSelectionIn):
    """Delete the chosen profiles."""
    return run_write_transaction(lambda s: delete_download_profiles(s, body))


@router.post("/which-episodes", dependencies=[requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW))], response_model=WhichEpisodesAPIRead)
def download_profiles_which_episodes(body: WhichEpisodesAPIRequest, request: Request):
    """How many of the Collection's indexed episodes each Which episodes line leaves out, and optionally which."""
    if body.example_collection is not None:
        if not deps.request_access(request).allows_source(body.example_collection.source_key):
            raise HTTPException(status_code=404, detail="Source not found")
        try:
            with example_session(body.example_collection.example()) as (s, collection, _examples):
                return count_which_episodes(s, collection, body)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Could not look up the newest episodes: {exc}") from exc
    with db_session() as s:
        collection = s.get(Collection, body.collection_id)
        if collection is None or not deps.request_access(request).allows_source(collection.source_key):
            raise HTTPException(status_code=404, detail="Collection not found")
        return count_which_episodes(s, collection, body)


@router.get("/skipped-by-filter/{collection_id}", dependencies=[requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.LIBRARY, Level.VIEW))], response_model=list[SkippedByFilterAPIRead])
def download_profiles_skipped_by_filter(collection_id: int, request: Request):
    """Episodes of the Collection that a Download Profile's own rules leave out, with the rule."""
    with db_session() as s:
        collection = s.get(Collection, collection_id)
        if collection is None or not deps.request_access(request).allows_source(collection.source_key):
            raise HTTPException(status_code=404, detail="Collection not found")
        return skipped_by_filter(s, collection_id)


@router.get("/waiting-for-countdown/{collection_id}", dependencies=[requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.LIBRARY, Level.VIEW))], response_model=list[WaitingForCountdownAPIRead])
def download_profiles_waiting_for_countdown(collection_id: int, request: Request):
    """Episodes of the Collection that a Download Profile downloads once their countdown is gone."""
    with db_session() as s:
        collection = s.get(Collection, collection_id)
        if collection is None or not deps.request_access(request).allows_source(collection.source_key):
            raise HTTPException(status_code=404, detail="Collection not found")
        return waiting_for_countdown(s, collection_id)


@router.get("/site-options/{collection_id}", dependencies=[requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW))], response_model=SiteOptionsAPIRead)
def download_profiles_site_options(collection_id: int, request: Request):
    """Choices only some sites offer, such as YouTube's auto-generated subtitles, for a saved Collection."""
    with db_session() as s:
        collection = s.get(Collection, collection_id)
        if collection is None or not deps.request_access(request).allows_source(collection.source_key):
            raise HTTPException(status_code=404, detail="Collection not found")
        site = collection_site(collection)
        return SiteOptionsAPIRead(
            settings=offered_settings(site, SiteSettingGroup.DOWNLOAD_PROFILE),
            profile_defaults=DownloadProfileDefaultsAPIRead.model_validate(download_profile_defaults(site)),
            upgrade_checks=UpgradeChecksAPIRead.model_validate(site.upgrade_checks),
            site_name=site.name, stream_methods=site.stream_methods,
            stream_video_heights=site.stream_video_heights, stream_proxy_choice=site.stream_proxy_choice,
            video_output_help=site.video_output_help,
            downloads=DownloadOptionsAPIRead.model_validate(site.downloads),
        )


@router.get("/auto-subtitles/{local_media_profile_id}", dependencies=[requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.LOCAL_MEDIA_PROFILES, Level.VIEW))], response_model=list[AutoSubtitlesUseAPIRead])
def download_profiles_auto_subtitles(local_media_profile_id: int, request: Request):
    """The YouTube Download Profiles that use a Local Media Profile, with their auto-generated subtitle choice."""
    with db_session() as s:
        return auto_subtitles_uses(s, local_media_profile_id, deps.request_access(request))


@router.get("/{download_profile_id}", dependencies=[requires_any((Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=DownloadProfileAPIRead)
def download_profile_detail(download_profile_id: int):
    """
    Retrieve a single download profile.
    """
    with db_session() as s:
        return get_download_profile(s, download_profile_id)


@router.post("", dependencies=[requires(Area.DOWNLOAD_PROFILES, Level.MANAGE)], response_model=DownloadProfileAPIRead, status_code=status.HTTP_201_CREATED)
def download_profiles_create(body: DownloadProfileAPICreate):
    """
    Create a new download profile.

    Creates a profile defining which episodes of a collection to download automatically.
    Returns the created profile with tracking information.
    """
    def work(s):
        return create_download_profile(s, body)

    return run_write_transaction(work)


@router.patch("/{download_profile_id}", dependencies=[requires(Area.DOWNLOAD_PROFILES, Level.MANAGE)], response_model=DownloadProfileAPIRead)
def download_profiles_update(download_profile_id: int, body: DownloadProfileAPIUpdate):
    """
    Update an existing download profile.
    """
    def work(s):
        return update_download_profile(s, download_profile_id, body)

    return run_write_transaction(work)


@router.delete("/{download_profile_id}", dependencies=[requires(Area.DOWNLOAD_PROFILES, Level.MANAGE)], response_model=DownloadProfileAPIRead)
def download_profiles_delete(download_profile_id: int):
    """
    Delete a download profile.

    Permanently removes the specified profile configuration.
    Returns the deleted profile's information for confirmation.
    """
    def work(s):
        return delete_download_profile(s, download_profile_id)

    return run_write_transaction(work)
