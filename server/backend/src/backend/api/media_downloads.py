from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from task_manager import cancel_task, prioritize_task

from backend.db import get_session
from backend.db.models import MediaDownload, TaskRun
from backend.schemas import MediaDownloadRead
from controller.workers import queue_download

router = APIRouter(prefix="/media-downloads", tags=["media-downloads"])


@router.get("", response_model=list[MediaDownloadRead])
def list_media_downloads(
    video_id: int | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
):
    statement = select(MediaDownload)
    if video_id is not None:
        statement = statement.where(MediaDownload.video_id == video_id)
    if status is not None:
        statement = statement.where(MediaDownload.status == status)
    return list(session.scalars(statement.order_by(MediaDownload.id.desc())))


@router.get("/{download_id}", response_model=MediaDownloadRead)
def get_media_download(download_id: int, session: Session = Depends(get_session)):
    artifact = session.get(MediaDownload, download_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Media download not found")
    return artifact


@router.post("/{download_id}/retry", response_model=dict, status_code=202)
def retry_media_download(download_id: int, session: Session = Depends(get_session)):
    artifact = session.get(MediaDownload, download_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Media download not found")
    if artifact.status not in {"failed", "cancelled", "missing"}:
        raise HTTPException(status_code=409, detail="Only failed, canceled, or missing downloads can be retried")
    if artifact.task_run_id is not None:
        current_run = session.get(TaskRun, artifact.task_run_id)
        if current_run is not None and current_run.status in {"scheduled", "queued", "running", "retry_scheduled"}:
            raise HTTPException(status_code=409, detail="This download already has active or scheduled work")
    run = queue_download(artifact.video_id, artifact.local_media_profile_id, reset_artifact=True)
    return {"status": "queued", "task_run_id": run.id}


@router.post("/{download_id}/cancel", response_model=dict, status_code=202)
def cancel_media_download(download_id: int, session: Session = Depends(get_session)):
    artifact = session.get(MediaDownload, download_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Media download not found")
    run = session.get(TaskRun, artifact.task_run_id) if artifact.task_run_id is not None else None
    if run is None or run.status in {"succeeded", "failed", "canceled"}:
        if artifact.status == "queued":
            artifact.status = "cancelled"
            artifact.error = "Cancelled"
            session.commit()
            return {"status": "cancelled", "task_run_id": artifact.task_run_id}
        raise HTTPException(status_code=409, detail="Download has no cancellable task run")
    if not cancel_task(run.id):
        raise HTTPException(status_code=409, detail="Download cannot be canceled")
    if artifact.status == "queued":
        artifact.status = "cancelled"
        artifact.error = "Cancelled"
        session.commit()
    return {"status": "cancellation_requested", "task_run_id": run.id}


@router.post("/{download_id}/prioritize", response_model=dict, status_code=202)
def prioritize_media_download(download_id: int, session: Session = Depends(get_session)):
    artifact = session.get(MediaDownload, download_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Media download not found")
    if artifact.task_run_id is None or not prioritize_task(artifact.task_run_id):
        raise HTTPException(status_code=409, detail="Only queued downloads can be prioritized")
    return {"status": "prioritized", "task_run_id": artifact.task_run_id}


@router.delete("/{download_id}", status_code=204)
def delete_media_download(download_id: int, session: Session = Depends(get_session)):
    artifact = session.get(MediaDownload, download_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Media download not found")
    if artifact.status in {"queued", "downloading"}:
        raise HTTPException(
            status_code=409,
            detail="Cancel the download and wait for it to stop before deleting it",
        )
    if artifact.task_run_id is not None:
        run = session.get(TaskRun, artifact.task_run_id)
        if run is not None and run.status in {"queued", "running", "retry_scheduled", "scheduled"}:
            raise HTTPException(
                status_code=409,
                detail="Cancel the active download and wait for it to stop before deleting it",
            )
    if artifact.file_path:
        path = Path(artifact.file_path)
        try:
            if path.is_file():
                path.unlink()
        except OSError as exc:
            raise HTTPException(status_code=409, detail=f"Could not delete downloaded file: {exc}") from exc
    session.delete(artifact)
    session.commit()
    return Response(status_code=204)


@router.get("/{download_id}/file")
def get_media_download_file(download_id: int, session: Session = Depends(get_session)):
    artifact = session.get(MediaDownload, download_id)
    if artifact is None or artifact.status != "downloaded" or not artifact.file_path:
        raise HTTPException(status_code=404, detail="Downloaded file not found")
    path = Path(artifact.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Downloaded file is missing from disk")
    return FileResponse(path, filename=path.name)
