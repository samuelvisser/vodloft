from __future__ import annotations

from backend.db import SessionLocal
from backend.services.downloads import download_video, ensure_media_download
from config import get_settings
from task_manager.registry import on_event, task
from ytdlp_client import YtDlpClient


def _client() -> YtDlpClient:
    return YtDlpClient(get_settings().yt_dlp.options)


def _progress(context, event: dict) -> None:
    context.check_cancelled()
    status = event.get("status")
    if status == "downloading":
        downloaded = int(event.get("downloaded_bytes") or 0)
        total = int(event.get("total_bytes") or event.get("total_bytes_estimate") or 0)
        progress = int(downloaded * 100 / total) if total else 0
        context.report(min(progress, 98), "Downloading")
    elif status == "finished":
        context.report(99, "Post-processing")


@on_event("video.download.requested", resource_type="video")
@task(
    "video.download",
    "Download video",
    "Runs a video download through yt-dlp using a Local Media Profile.",
    allowed_resource_types=("video",),
    tracks_progress=True,
    max_concurrency=get_settings().task_manager.download_max_concurrency,
)
def download_video_worker(context, _resource_type: str, video_id: int, payload: dict):
    local_media_profile_id = int(payload.get("local_media_profile_id") or 0)
    if local_media_profile_id <= 0:
        raise ValueError("local_media_profile_id is required")
    reset_artifact = bool(payload.get("reset_artifact", False))

    context.report(1, "Preparing download")
    with SessionLocal() as session:
        artifact = ensure_media_download(
            session,
            video_id,
            local_media_profile_id,
            reset=reset_artifact,
        )
        artifact.task_run_id = context.run_id
        session.commit()
        result = download_video(
            session,
            _client(),
            video_id,
            local_media_profile_id,
            progress_hook=lambda event: _progress(context, event),
        )
    context.report(100, "Downloaded")
    context.emit(
        "video.downloaded",
        resource_type="video",
        resource_id=video_id,
        payload={"local_media_profile_id": local_media_profile_id, **result},
    )
    return result
