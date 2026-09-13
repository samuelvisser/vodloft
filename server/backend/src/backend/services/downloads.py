from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from config import get_settings
from sqlalchemy import select
from sqlalchemy.orm import Session
from task_manager import TaskCancelled
from ytdlp_client import DownloadOptions, YtDlpClient

from backend.db.models import LocalMediaProfile, MediaDownload, Video


def get_media_download(
    session: Session,
    video_id: int,
    local_media_profile_id: int,
) -> MediaDownload | None:
    return session.scalar(
        select(MediaDownload).where(
            MediaDownload.video_id == video_id,
            MediaDownload.local_media_profile_id == local_media_profile_id,
        )
    )


def ensure_media_download(
    session: Session,
    video_id: int,
    local_media_profile_id: int,
    *,
    reset: bool = False,
) -> MediaDownload:
    artifact = get_media_download(session, video_id, local_media_profile_id)
    if artifact is None:
        artifact = MediaDownload(
            video_id=video_id,
            local_media_profile_id=local_media_profile_id,
            status="queued",
        )
        session.add(artifact)
        session.flush()
    elif reset:
        artifact.status = "queued"
        artifact.error = None
        artifact.downloaded_bytes = None
    return artifact


def download_video(
    session: Session,
    client: YtDlpClient,
    video_id: int,
    local_media_profile_id: int,
    progress_hook=None,
) -> dict[str, str | int | None]:
    video = session.get(Video, video_id)
    profile = session.get(LocalMediaProfile, local_media_profile_id)
    if video is None:
        raise LookupError("Video not found")
    if profile is None:
        raise LookupError("Local media profile not found")

    artifact = ensure_media_download(session, video_id, local_media_profile_id)
    artifact.status = "downloading"
    artifact.error = None
    session.commit()

    template = profile.output_template
    settings = get_settings()
    if template.startswith("/downloads/") and settings.download_root != "/downloads":
        template = settings.download_root.rstrip("/") + template[len("/downloads"):]

    def on_progress(event):
        downloaded = event.get("downloaded_bytes")
        if isinstance(downloaded, int):
            artifact.downloaded_bytes = downloaded
        if progress_hook is not None:
            progress_hook(event)

    try:
        result = client.download(
            video.source_url,
            DownloadOptions(
                output_template=template,
                format_selector=profile.preferred_format,
                merge_output_format=profile.merge_output_format,
                audio_format=profile.audio_format,
                write_subtitles=profile.write_subtitles,
                embed_metadata=profile.embed_metadata,
                embed_thumbnail=profile.embed_thumbnail,
            ),
            progress_hook=on_progress,
        )
    except TaskCancelled:
        artifact.status = "cancelled"
        artifact.error = "Cancelled"
        session.commit()
        raise
    except Exception as exc:
        artifact.status = "failed"
        artifact.error = str(exc)
        session.commit()
        raise

    artifact.status = "downloaded"
    artifact.file_path = result.filepath
    artifact.format_downloaded = result.format_id or result.ext
    artifact.error = None
    artifact.downloaded_at = datetime.now(timezone.utc)
    if result.filepath:
        try:
            artifact.downloaded_bytes = Path(result.filepath).stat().st_size
        except OSError:
            pass
    session.commit()
    session.refresh(artifact)
    return {
        "media_download_id": artifact.id,
        "path": artifact.file_path,
        "format": artifact.format_downloaded,
    }
