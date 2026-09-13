from __future__ import annotations

from typing import Any

from config import get_settings
from task_manager import TaskContext, TaskManager, TaskSnapshot
from ytdlp_client import YtDlpClient

from backend.db import SessionLocal
from backend.db.models import StreamProfile, Video
from backend.services.downloads import download_video
from backend.services.library import sync_collection

_settings = get_settings()
_tasks = TaskManager(max_workers=_settings.worker_threads)


def _client() -> YtDlpClient:
    return YtDlpClient(_settings.yt_dlp.options)


def queue_sync(collection_id: int) -> TaskSnapshot:
    def run(context: TaskContext):
        context.report(1, "Reading collection metadata")
        with SessionLocal() as session:
            collection = sync_collection(session, _client(), collection_id)
            context.report(100, f"Synced {len(collection.videos)} videos")
            return {"collection_id": collection.id, "video_count": len(collection.videos)}

    return _tasks.submit(f"Sync collection {collection_id}", run)


def _download_progress(context: TaskContext, event: dict[str, Any]) -> None:
    context.check_cancelled()
    status = event.get("status")
    if status == "downloading":
        downloaded = event.get("downloaded_bytes") or 0
        total = event.get("total_bytes") or event.get("total_bytes_estimate") or 0
        progress = int(downloaded * 100 / total) if total else 0
        context.report(progress, "Downloading")
    elif status == "finished":
        context.report(99, "Post-processing")


def queue_download(video_id: int, profile_id: int) -> TaskSnapshot:
    def run(context: TaskContext):
        with SessionLocal() as session:
            return download_video(
                session,
                _client(),
                video_id,
                profile_id,
                progress_hook=lambda event: _download_progress(context, event),
            )

    return _tasks.submit(f"Download video {video_id}", run)


def resolve_stream(video_id: int, profile_id: int):
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        profile = session.get(StreamProfile, profile_id)
        if video is None:
            raise LookupError("Video not found")
        if profile is None:
            raise LookupError("Stream profile not found")
        return _client().resolve_stream(video.source_url, profile.format_selector)


def list_tasks() -> list[TaskSnapshot]:
    return _tasks.list()


def get_task(task_id: str) -> TaskSnapshot | None:
    return _tasks.get(task_id)


def cancel_task(task_id: str) -> bool:
    return _tasks.cancel(task_id)
