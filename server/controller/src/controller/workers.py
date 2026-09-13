from __future__ import annotations

from config import get_settings
from sqlalchemy import select
from task_manager import cancel_task as cancel_run
from task_manager import submit_task
from ytdlp_client import StreamTarget, YtDlpClient

from backend.db import SessionLocal
from backend.db.models import MediaDownload, StreamProfile, TaskRun, Video, collection_videos
from backend.services.downloads import ensure_media_download


def _client() -> YtDlpClient:
    return YtDlpClient(get_settings().yt_dlp.options)


def queue_download(video_id: int, local_media_profile_id: int, *, reset_artifact: bool = True) -> TaskRun:
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
        artifact_id = artifact.id
        profile_id = artifact.local_media_profile_id
    run = submit_task(
        "video.download",
        resource_type="video",
        resource_id=video_id,
        payload={
            "local_media_profile_id": profile_id,
            "reset_artifact": reset_artifact,
        },
        dedupe_key=f"video.download:{video_id}:{profile_id}",
        source="api",
    )
    with SessionLocal() as session:
        artifact = session.get(MediaDownload, artifact_id)
        if artifact is not None:
            artifact.task_run_id = run.id
            session.commit()
    return run


def queue_sync(collection_id: int) -> TaskRun:
    return submit_task(
        "collection.sync",
        resource_type="collection",
        resource_id=collection_id,
        source="api",
    )


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

        source_url = video.source_url
        selector = profile.format_selector
    return _client().resolve_stream(source_url, selector)


def list_tasks(limit: int = 100) -> list[TaskRun]:
    with SessionLocal() as session:
        return list(session.scalars(select(TaskRun).order_by(TaskRun.id.desc()).limit(limit)))


def get_task(task_id: int) -> TaskRun | None:
    with SessionLocal() as session:
        return session.get(TaskRun, task_id)


def cancel_task(task_id: int) -> bool:
    return cancel_run(task_id)
