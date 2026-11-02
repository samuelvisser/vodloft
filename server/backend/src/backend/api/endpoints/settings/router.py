from fastapi import APIRouter, HTTPException, status

from backend.api.models.operations import TaskOperationAccepted
from backend.api.models.settings import LibraryDefaultsAPIRead, SettingsAPIRead, SettingsAPIUpdate
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
