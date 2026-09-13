from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from backend.db import SessionLocal
from backend.db.models import Collection, DownloadProfile, MediaDownload, TaskOperation
from backend.services.downloads import ensure_media_download
from backend.services.library import sync_collection as sync_collection_service
from config import get_settings
from task_manager.registry import on_event, on_interval, task
from task_manager.types import OperationSource, TaskResult
from ytdlp_client import YtDlpClient


def _client() -> YtDlpClient:
    return YtDlpClient(get_settings().yt_dlp.options)


@on_interval(get_settings().scheduler.collection_sync_interval_minutes, resource_type="system", resource_id=0)
@task(
    "collections.sync_all",
    "Synchronize all collections",
    "Queues the durable synchronization worker for every channel and playlist.",
    allowed_resource_types=("system",),
    tracks_progress=True,
)
def sync_all_collections(context, _resource_type: str, _resource_id: int, _payload: dict):
    with SessionLocal() as session:
        collection_ids = list(session.scalars(select(Collection.id).order_by(Collection.id)))
    total = len(collection_ids)
    if not total:
        return TaskResult({"collections_queued": 0}, "No collections to synchronize")
    operation = context.create_operation(
        "Synchronize collections",
        source=OperationSource.SCHEDULE.value,
        meta={"collection_count": total},
    )
    for index, collection_id in enumerate(collection_ids, start=1):
        context.check_cancelled()
        context.submit(
            "collection.sync",
            resource_type="collection",
            resource_id=collection_id,
            operation_id=operation.id,
            source=OperationSource.SYSTEM.value,
        )
        context.report(int(index * 100 / total), f"Queued {index} of {total} collections")
    return {"collections_queued": total, "operation_id": operation.id}


@on_event("collection.added", resource_type="collection")
@task(
    "collection.sync",
    "Synchronize collection",
    "Refreshes channel/playlist metadata and video membership through yt-dlp.",
    allowed_resource_types=("collection",),
    tracks_progress=True,
)
def sync_collection_worker(context, _resource_type: str, collection_id: int, _payload: dict):
    context.report(2, "Reading collection metadata")
    with SessionLocal() as session:
        collection = session.get(Collection, collection_id)
        if collection is None:
            raise LookupError("Collection not found")
        before_ids = {video.id for video in collection.videos}
        collection = sync_collection_service(session, _client(), collection_id)
        after_ids = {video.id for video in collection.videos}
        title = collection.title
        video_count = len(after_ids)
    new_ids = sorted(after_ids - before_ids)
    context.report(90, "Collection metadata synchronized")
    context.emit(
        "collection.synced",
        resource_type="collection",
        resource_id=collection_id,
        payload={"new_video_ids": new_ids, "video_count": video_count},
    )
    context.report(100, f"Synchronized {video_count} videos")
    return {
        "collection_id": collection_id,
        "title": title,
        "video_count": video_count,
        "new_video_ids": new_ids,
    }


@on_event("download_profile.changed", resource_type="collection")
@on_event("collection.synced", resource_type="collection")
@task(
    "collection.plan_downloads",
    "Plan collection downloads",
    "Queues missing artifacts for each enabled collection download profile.",
    allowed_resource_types=("collection",),
    tracks_progress=True,
)
def plan_collection_downloads(context, _resource_type: str, collection_id: int, _payload: dict):
    pairs: list[tuple[int, int, int]] = []
    with SessionLocal() as session:
        collection = session.get(Collection, collection_id)
        if collection is None:
            raise LookupError("Collection not found")
        profiles = list(
            session.scalars(
                select(DownloadProfile).where(
                    DownloadProfile.collection_id == collection_id,
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
                    artifact = ensure_media_download(session, video.id, profile.local_media_profile_id, reset=False)
                    pairs.append((artifact.id, video.id, profile.local_media_profile_id))
                elif artifact.status in {"queued", "missing"}:
                    pairs.append((artifact.id, video.id, profile.local_media_profile_id))
        session.commit()
        title = collection.title

    if not pairs:
        return TaskResult({"downloads_queued": 0}, "No missing downloads")
    operation = context.create_operation(
        f"Download missing media for {title}",
        source=OperationSource.EVENT.value,
        meta={"collection_id": collection_id},
    )
    total = len(pairs)
    linked = 0
    for index, (artifact_id, video_id, local_media_profile_id) in enumerate(pairs, start=1):
        context.check_cancelled()
        run = context.submit(
            "video.download",
            resource_type="video",
            resource_id=video_id,
            payload={"local_media_profile_id": local_media_profile_id, "reset_artifact": False},
            operation_id=operation.id,
            dedupe_key=f"video.download:{video_id}:{local_media_profile_id}",
            source=OperationSource.EVENT.value,
        )
        if run.operation_id == operation.id:
            linked += 1
        with SessionLocal() as session:
            artifact = session.get(MediaDownload, artifact_id)
            if artifact is not None:
                artifact.task_run_id = run.id
                session.commit()
        context.report(int(index * 100 / total), f"Queued {index} of {total} downloads")
    if linked == 0:
        with SessionLocal() as session:
            stored = session.get(TaskOperation, operation.id)
            if stored is not None:
                stored.status = "succeeded"
                stored.finished_at = datetime.now(timezone.utc)
                session.commit()
    return {"downloads_queued": linked, "downloads_already_queued": total - linked, "operation_id": operation.id}
