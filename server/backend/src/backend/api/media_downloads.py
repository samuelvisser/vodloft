from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db import get_session
from backend.db.models import MediaDownload
from backend.schemas import MediaDownloadRead

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


@router.get("/{download_id}/file")
def get_media_download_file(download_id: int, session: Session = Depends(get_session)):
    artifact = session.get(MediaDownload, download_id)
    if artifact is None or artifact.status != "downloaded" or not artifact.file_path:
        raise HTTPException(status_code=404, detail="Downloaded file not found")
    path = Path(artifact.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Downloaded file is missing from disk")
    return FileResponse(path, filename=path.name)
