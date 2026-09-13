from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import get_settings, save_settings
from backend.db import get_session
from backend.schemas.settings import ApplicationSettingsRead, ApplicationSettingsUpdate, RuntimeSettingsUpdate
from backend.security import ensure_application_settings

router = APIRouter(prefix="/settings", tags=["settings"])


def _read(settings) -> ApplicationSettingsRead:
    runtime = get_settings()
    return ApplicationSettingsRead(
        onboarding_completed=settings.onboarding_completed,
        alembic_version_num=settings.alembic_version_num,
        auth_enabled=settings.auth_enabled,
        admin_username=settings.admin_username,
        rss_token=settings.rss_token,
        rss_item_limit=settings.rss_item_limit,
        worker_threads=runtime.worker_threads,
        scheduler_enabled=runtime.scheduler.enabled,
        collection_sync_interval_minutes=runtime.scheduler.collection_sync_interval_minutes,
        verification_interval_minutes=runtime.scheduler.verification_interval_minutes,
        default_max_retries=runtime.task_manager.default_max_retries,
        retry_backoff_base_seconds=runtime.task_manager.retry_backoff_base_seconds,
        retry_backoff_max_seconds=runtime.task_manager.retry_backoff_max_seconds,
        stalled_timeout_minutes=runtime.task_manager.stalled_timeout_minutes,
        download_max_concurrency=runtime.task_manager.download_max_concurrency,
        yt_dlp_options=dict(runtime.yt_dlp.options),
    )


@router.get("", response_model=ApplicationSettingsRead)
def read_settings(session: Session = Depends(get_session)):
    return _read(ensure_application_settings(session))


@router.put("", response_model=ApplicationSettingsRead)
def update_settings(payload: ApplicationSettingsUpdate, session: Session = Depends(get_session)):
    settings = ensure_application_settings(session)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("auth_enabled") and not settings.admin_password_hash:
        raise HTTPException(status_code=422, detail="Set an administrator password before enabling authentication")
    if "admin_username" in changes:
        changes["admin_username"] = (changes["admin_username"] or "").strip() or "admin"
    for key, value in changes.items():
        setattr(settings, key, value)
    session.commit()
    session.refresh(settings)
    return _read(settings)


@router.post("/rss-token/rotate", response_model=ApplicationSettingsRead)
def rotate_rss_token(session: Session = Depends(get_session)):
    settings = ensure_application_settings(session)
    settings.rss_token = secrets.token_urlsafe(32)
    session.commit()
    session.refresh(settings)
    return _read(settings)


@router.put("/runtime", response_model=ApplicationSettingsRead)
def update_runtime_settings(payload: RuntimeSettingsUpdate, session: Session = Depends(get_session)):
    current = get_settings()
    changes = payload.model_dump(exclude_unset=True)

    scheduler_changes = {}
    for key in ("collection_sync_interval_minutes", "verification_interval_minutes"):
        if key in changes:
            scheduler_changes[key] = changes.pop(key)
    if "scheduler_enabled" in changes:
        scheduler_changes["enabled"] = changes.pop("scheduler_enabled")

    task_changes = {}
    for key in (
        "default_max_retries",
        "retry_backoff_base_seconds",
        "retry_backoff_max_seconds",
        "stalled_timeout_minutes",
        "download_max_concurrency",
    ):
        if key in changes:
            task_changes[key] = changes.pop(key)

    yt_dlp_options = changes.pop("yt_dlp_options", None)
    updated = current.model_copy(
        update={
            **changes,
            "scheduler": current.scheduler.model_copy(update=scheduler_changes),
            "task_manager": current.task_manager.model_copy(update=task_changes),
            "yt_dlp": current.yt_dlp.model_copy(update={"options": yt_dlp_options}) if yt_dlp_options is not None else current.yt_dlp,
        }
    )
    # Revalidate the complete structure before replacing config.yml atomically.
    updated = type(current).model_validate(updated.model_dump(mode="python"))
    save_settings(updated)
    return _read(ensure_application_settings(session))
