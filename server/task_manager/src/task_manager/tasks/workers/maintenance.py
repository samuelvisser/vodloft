from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from backend.db import SessionLocal
from backend.db.models import MediaDownload
from config import get_settings
from task_manager.registry import on_interval, task
from task_manager.runtime import get_runtime
from task_manager.types import TaskResult


@on_interval(get_settings().scheduler.verification_interval_minutes, resource_type="system", resource_id=0)
@task(
    "downloads.verify",
    "Verify downloads",
    "Checks the persistent media ledger against files on disk and marks missing artifacts.",
    allowed_resource_types=("system",),
    tracks_progress=True,
)
def verify_downloads(context, _resource_type: str, _resource_id: int, _payload: dict):
    with SessionLocal() as session:
        artifacts = list(
            session.scalars(
                select(MediaDownload).where(MediaDownload.status == "downloaded").order_by(MediaDownload.id)
            )
        )
        total = len(artifacts)
        missing = 0
        for index, artifact in enumerate(artifacts, start=1):
            context.check_cancelled()
            path = Path(artifact.file_path) if artifact.file_path else None
            if path is None or not path.is_file():
                artifact.status = "missing"
                artifact.error = "Downloaded file is missing from disk"
                missing += 1
                context.emit(
                    "download.missing",
                    resource_type="video",
                    resource_id=artifact.video_id,
                    payload={"media_download_id": artifact.id},
                )
            else:
                try:
                    artifact.downloaded_bytes = path.stat().st_size
                except OSError:
                    pass
            if total:
                context.report(int(index * 100 / total), f"Verified {index} of {total}")
        session.commit()
    return {"verified": total, "missing": missing}


@on_interval(5, resource_type="system", resource_id=0)
@task(
    "tasks.reconcile_stalled",
    "Reconcile stalled tasks",
    "Fails task runs whose progress has not changed within the configured timeout.",
    allowed_resource_types=("system",),
    tracks_progress=False,
    default_max_retries=0,
)
def reconcile_stalled(_context, _resource_type: str, _resource_id: int, _payload: dict):
    count = get_runtime().mark_stalled_runs()
    return TaskResult({"stalled_runs": count}, f"Marked {count} stalled task run(s)")
