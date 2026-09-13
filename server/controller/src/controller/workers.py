from __future__ import annotations

from threading import RLock
from typing import Any

from config import get_settings
from sqlalchemy import select
from task_manager import TaskContext, TaskManager, TaskSnapshot, TaskStatus
from ytdlp_client import StreamTarget, YtDlpClient

from backend.db import SessionLocal
from backend.db.models import DownloadProfile, MediaDownload, StreamProfile, Video, collection_videos
from backend.services.downloads import download_video, ensure_media_download
from backend.services.library import sync_collection

_settings = get_settings()
_tasks = TaskManager(max_workers=_settings.worker_threads)
_download_task_ids: dict[tuple[int, int], str] = {}
_sync_task_ids: dict[int, str] = {}
_task_key_lock = RLock()


def _client() -> YtDlpClient:
    return YtDlpClient(_settings.yt_dlp.options)


def _is_active(task_id: str | None) -> TaskSnapshot | None:
    if not task_id:
        return None
    snapshot = _tasks.get(task_id)
    if snapshot and snapshot.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
        return snapshot
    return None


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


def queue_download(
    video_id: int,
    local_media_profile_id: int,
    *,
    reset_artifact: bool = True,
) -> TaskSnapshot:
    key = (video_id, local_media_profile_id)
    with _task_key_lock:
        if existing := _is_active(_download_task_ids.get(key)):
            return existing

        with SessionLocal() as session:
            if session.get(Video, video_id) is None:
                raise LookupError("Video not found")
            artifact = ensure_media_download(
                session,
                video_id,
                local_media_profile_id,
                reset=reset_artifact,
            )
            session.commit()
            local_media_profile_id = artifact.local_media_profile_id

        def run(context: TaskContext):
            with SessionLocal() as session:
                return download_video(
                    session,
                    _client(),
                    video_id,
                    local_media_profile_id,
                    progress_hook=lambda event: _download_progress(context, event),
                )

        snapshot = _tasks.submit(f"Download video {video_id}", run)
        _download_task_ids[key] = snapshot.id
        return snapshot


def queue_sync(collection_id: int) -> TaskSnapshot:
    with _task_key_lock:
        if existing := _is_active(_sync_task_ids.get(collection_id)):
            return existing

        def run(context: TaskContext):
            context.report(1, "Reading collection metadata")
            scheduled: list[tuple[int, int]] = []
            with SessionLocal() as session:
                collection = sync_collection(session, _client(), collection_id)
                profiles = list(
                    session.scalars(
                        select(DownloadProfile).where(
                            DownloadProfile.collection_id == collection.id,
                            DownloadProfile.enable_profile.is_(True),
                        )
                    )
                )
                for profile in profiles:
                    for video in collection.videos:
                        artifact = session.scalar(
                            select(MediaDownload).where(
                                MediaDownload.video_id == video.id,
                                MediaDownload.local_media_profile_id == profile.local_media_profile_id,
                            )
                        )
                        if artifact is None:
                            ensure_media_download(
                                session,
                                video.id,
                                profile.local_media_profile_id,
                                reset=False,
                            )
                            scheduled.append((video.id, profile.local_media_profile_id))
                        elif artifact.status == "queued":
                            scheduled.append((video.id, profile.local_media_profile_id))
                session.commit()
                video_count = len(collection.videos)

            for video_id, profile_id in scheduled:
                queue_download(video_id, profile_id, reset_artifact=False)

            context.report(100, f"Synced {video_count} videos")
            return {
                "collection_id": collection_id,
                "video_count": video_count,
                "downloads_queued": len(scheduled),
            }

        snapshot = _tasks.submit(f"Sync collection {collection_id}", run)
        _sync_task_ids[collection_id] = snapshot.id
        return snapshot


def resolve_stream(video_id: int, profile_id: int) -> StreamTarget:
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        profile = session.get(StreamProfile, profile_id)
        if video is None:
            raise LookupError("Video not found")
        if profile is None or not profile.enable_profile:
            raise LookupError("Stream profile not found")
        if profile.collection_id is not None:
            belongs = session.scalar(
                select(collection_videos.c.video_id).where(
                    collection_videos.c.collection_id == profile.collection_id,
                    collection_videos.c.video_id == video.id,
                )
            )
            if belongs is None:
                raise LookupError("Video does not belong to this stream profile's collection")

        if profile.use_downloads:
            artifact = session.scalar(
                select(MediaDownload)
                .where(MediaDownload.video_id == video.id, MediaDownload.status == "downloaded")
                .order_by(MediaDownload.downloaded_at.desc())
            )
            if artifact is not None and artifact.file_path:
                return StreamTarget(
                    url=f"/api/media-downloads/{artifact.id}/file",
                    format_id=artifact.format_downloaded,
                )

        return _client().resolve_stream(video.source_url, profile.format_selector)


def list_tasks() -> list[TaskSnapshot]:
    return _tasks.list()


def get_task(task_id: str) -> TaskSnapshot | None:
    return _tasks.get(task_id)


def cancel_task(task_id: str) -> bool:
    return _tasks.cancel(task_id)
