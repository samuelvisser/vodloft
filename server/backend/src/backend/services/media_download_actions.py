"""Inherited media download actions shared by API and task workers."""

from fastapi import HTTPException

from backend.db import get_session
from backend.db.models.media_download import MediaDownloadBase
from backend.services.media_download_history import record_media_download_history
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.media_download_history_types import MediaDownloadHistoryAction
from task_manager.scheduler.types import OperationSource
from task_manager.tasks.media_download_operations import (
    cancel_media_download_operation, create_media_download_operation,
    dispatch_queued_media_download_operations, get_active_media_download_operation,
    prepare_media_download_artifact,
)
from task_manager.tasks.workers.file_watcher.service import resolve_media_download_file


def reset_media_download(session, media_download_id: int) -> MediaDownloadBase:
    download = session.get(MediaDownloadBase, media_download_id)
    if download is None:
        raise HTTPException(404, "Media download not found")
    if get_active_media_download_operation(session, download.id) is not None:
        raise HTTPException(409, "This download already has an active operation")
    if download.artifact_status != MediaDownloadArtifactStatus.ABSENT.value:
        resolve_media_download_file(session, download)
    prepare_media_download_artifact(session, download)
    session.flush()
    return download


def retry_media_download_action(media_download_id: int, *,
        source: str = OperationSource.UI.value,
        reuse_matching_active: bool = False) -> str:
    active_operation_id = None
    with get_session() as session:
        download = session.get(MediaDownloadBase, media_download_id)
        if download is None:
            raise HTTPException(404, "Media download not found")
        record_media_download_history(session, media_download_id,
            MediaDownloadHistoryAction.RETRY_REQUESTED, metadata={"source": source})
        session.commit()
        active = get_active_media_download_operation(session, media_download_id)
        if active is not None:
            if reuse_matching_active and active.source == source:
                return active.id
            active_operation_id = active.id
        is_redownload = (download.downloaded_at is not None or
            download.artifact_status in {"available", "missing", "corrupted"})
    if active_operation_id is not None:
        cancel_media_download_operation(active_operation_id,
            reason="Replaced by retry", acknowledge=True)
    with get_session() as session:
        try:
            download = reset_media_download(session, media_download_id)
            operation = create_media_download_operation(session, download,
                source=source, is_redownload=is_redownload)
            dispatch_queued_media_download_operations(session)
            operation_id = operation.id
            session.commit()
            return operation_id
        except Exception:
            session.rollback()
            raise


def cancel_media_download_action(media_download_id: int, *,
        allow_inactive: bool = False, missing_ok: bool = False) -> int | None:
    operation_id = None
    with get_session() as session:
        download = session.get(MediaDownloadBase, media_download_id)
        if download is None:
            if missing_ok:
                return None
            raise HTTPException(404, "Media download not found")
        operation = get_active_media_download_operation(session, media_download_id)
        if operation is None:
            if not allow_inactive:
                raise HTTPException(409, "This download is not currently in progress")
        else:
            operation_id = operation.id
    if operation_id is not None:
        try:
            cancel_media_download_operation(operation_id,
                reason="Canceled by user", acknowledge=True)
        except ValueError as exc:
            if not allow_inactive:
                raise HTTPException(409, "This download is not currently in progress") from exc
    with get_session() as session:
        download = session.get(MediaDownloadBase, media_download_id)
        if download is None:
            if missing_ok:
                return None
            raise HTTPException(404, "Media download not found")
        download.automatic_retry_suppressed = (
            download.artifact_status != MediaDownloadArtifactStatus.AVAILABLE.value)
        session.commit()
    with get_session() as session:
        replacement = get_active_media_download_operation(session, media_download_id)
        replacement_id = (replacement.id if replacement is not None and
            replacement.source == OperationSource.SYSTEM.value else None)
    if replacement_id is not None:
        try:
            cancel_media_download_operation(replacement_id,
                reason="Canceled by user", acknowledge=True)
        except ValueError:
            pass
    return media_download_id


def delete_media_download_artifact_action(media_download_id: int, *, missing_ok: bool = False) -> bool:
    if cancel_media_download_action(media_download_id, allow_inactive=True,
                                    missing_ok=missing_ok) is None:
        return False
    with get_session() as session:
        download = session.get(MediaDownloadBase, media_download_id)
        if download is None:
            if missing_ok:
                return False
            raise HTTPException(404, "Media download not found")
        prepare_media_download_artifact(session, download)
        download.automatic_retry_suppressed = True
        session.commit()
        return True
