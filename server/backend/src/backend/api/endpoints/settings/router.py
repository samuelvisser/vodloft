from fastapi import APIRouter, HTTPException, status

from backend.api.models.operations import TaskOperationAccepted
from backend.api.models.settings import (
    LibraryDefaultsAPIRead, SettingsAPIRead, SettingsAPIUpdate, SpeedLimitStatusRead,
)
from backend.api.models.site_refresh import SiteRefreshAPIRead, SiteRefreshAPIUpdate
from backend.services import speed_limit
from backend.services.site_refresh import UnknownSiteError, list_site_refresh, set_site_refresh
from config import get_settings
from backend.app import db_session
from backend.services.collection_assets import request_collection_asset_reconciliation
from .service import (
    SettingsManagedByEnvironmentError,
    SettingsPersistenceError,
    get_ui_settings,
    save_ui_settings,
    run_cron_job_now,
)
from backend.security.access import Area, Level
from backend.security.deps import requires, requires_any


router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("", dependencies=[requires(Area.SETTINGS, Level.MANAGE)], response_model=SettingsAPIRead)
def settings_get():
    """Return all settings intentionally exposed by the VODLoft UI."""
    return get_ui_settings()


@router.get(
    "/library-defaults",
    dependencies=[requires_any((Area.LIBRARY, Level.VIEW), (Area.LOCAL_MEDIA_PROFILES, Level.VIEW))],
    response_model=LibraryDefaultsAPIRead,
)
def library_defaults():
    """What Local Media Profiles fall back to, and when episodes without media are deleted."""
    settings = get_settings()
    return LibraryDefaultsAPIRead(
        download_mode=settings.download_settings.download_mode,
        thumbnail_mode=settings.download_settings.thumbnail_mode,
        metadata_mode=settings.download_settings.metadata_mode,
        no_usable_media_delete_after_minutes=settings.episode_status_timing.no_usable_media_delete_after_minutes,
    )


@router.get("/speed-limit", dependencies=[requires(Area.SETTINGS, Level.MANAGE)], response_model=SpeedLimitStatusRead)
def settings_speed_limit():
    """The download speed limit as it applies right now, and the connection speed VODLoft measured."""
    return SpeedLimitStatusRead.model_validate(speed_limit.status())


@router.get("/site-refresh", dependencies=[requires(Area.SETTINGS, Level.MANAGE)], response_model=list[SiteRefreshAPIRead])
def site_refresh_list():
    """The metadata refresh schedule of every Site VODLoft has seen."""
    with db_session() as s:
        return [SiteRefreshAPIRead.model_validate(site) for site in list_site_refresh(s)]


@router.put("/site-refresh/{key}", dependencies=[requires(Area.SETTINGS, Level.MANAGE)], response_model=SiteRefreshAPIRead)
def site_refresh_update(key: str, body: SiteRefreshAPIUpdate):
    """Choose the schedule a Site's items follow while VODLoft looks them up again, and whether its upcoming
    and live videos are added."""
    with db_session() as s:
        try:
            result = set_site_refresh(s, key, body.refresh_mode, body.refresh_intervals, body.pending_checks)
        except UnknownSiteError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        read = SiteRefreshAPIRead.model_validate(result)
        s.commit()
        return read


@router.put("", dependencies=[requires(Area.SETTINGS, Level.MANAGE)], response_model=SettingsAPIRead)
def settings_update(body: SettingsAPIUpdate):
    """Persist only explicitly changed UI fields into config.yml."""
    try:
        result = save_ui_settings(body)
    except SettingsManagedByEnvironmentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SettingsPersistenceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if set(body.changed_fields) & {
        "downloadSettings.downloadCollectionAssets", "downloadSettings.collectionArtworkFallbackFormat",
        "downloadSettings.downloadRoot", "downloadSettings.filenameRestrictionMode",
        "downloadSettings.ffmpegPath",
    }:
        with db_session() as session:
            request_collection_asset_reconciliation(session)
            session.commit()
    return result


@router.post(
    "/cron/{job}/run",
    dependencies=[requires(Area.SETTINGS, Level.MANAGE)],
    response_model=TaskOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def settings_cron_run(job: str):
    """Run one configured cron job immediately as a TaskOperation."""
    with db_session() as session:
        try:
            result = run_cron_job_now(session, job)
            session.commit()
            return result
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception:
            session.rollback()
            raise
