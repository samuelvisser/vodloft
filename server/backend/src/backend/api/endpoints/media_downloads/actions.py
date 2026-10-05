from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.models.media_download import MediaDownloadAPIRead
from backend.db import get_session
from backend.db.models.media_download import MediaDownloadBase
from backend.services.media_download_actions import (
    retry_media_download_action,
    delete_media_download_artifact_action,
    cancel_media_download_action as _cancel_download,
)
from task_manager.scheduler.operation_factory import create_operation
from task_manager.scheduler.operations import queue_operation_target_dispatch
from task_manager.tasks.media_download_operations import attach_redownload_dependencies
from .operations import _BulkMediaDownloadOperation


def cancel_media_download_action(media_download_id: int, *,
        allow_inactive: bool = False, missing_ok: bool = False) -> MediaDownloadAPIRead | None:
    result = _cancel_download(media_download_id,
        allow_inactive=allow_inactive, missing_ok=missing_ok)
    if result is None:
        return None
    with get_session() as session:
        return MediaDownloadAPIRead.model_validate(session.get(MediaDownloadBase, result))


def queue_bulk_media_download_operation(
        s: Session,
        operation: _BulkMediaDownloadOperation,
) -> dict[str, bool | int | str]:
    """Validate selected rows, create one operation, and dispatch its row targets."""
    ids = operation.media_download_ids
    if not ids:
        raise HTTPException(status_code=422, detail="At least one media download is required")

    downloads = list(s.scalars(
        select(MediaDownloadBase)
        .where(MediaDownloadBase.id.in_(ids))
        .order_by(MediaDownloadBase.id.asc())
    ))
    downloads_by_id = {download.id: download for download in downloads}
    missing_ids = [media_download_id for media_download_id in ids if media_download_id not in downloads_by_id]
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Media download {missing_ids[0]} not found",
        )

    queued_operation = create_operation(s, operation)
    if operation.action == "retry":
        attach_redownload_dependencies(
            s,
            queued_operation,
            tuple(downloads_by_id[media_download_id] for media_download_id in ids),
        )
    else:
        for media_download_id in ids:
            queue_operation_target_dispatch(
                s,
                queued_operation.id,
                f"media_download:{media_download_id}",
            )

    return {
        "queued": True,
        "downloads_queued": len(ids),
        "operation_id": queued_operation.id,
    }
