from __future__ import annotations

from sqlalchemy import select
from task_manager import TaskScheduler

from backend.db import SessionLocal
from backend.db.models import Collection
from config import get_settings

from .workers import queue_sync

_scheduler: TaskScheduler | None = None


def queue_all_collections() -> None:
    with SessionLocal() as session:
        collection_ids = list(session.scalars(select(Collection.id)))
    for collection_id in collection_ids:
        queue_sync(collection_id)


def start_scheduler() -> TaskScheduler | None:
    global _scheduler
    settings = get_settings()
    if not settings.scheduler.enabled:
        return None
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    scheduler = TaskScheduler()
    scheduler.add_interval_job(
        "sync_collections",
        queue_all_collections,
        minutes=settings.scheduler.collection_sync_interval_minutes,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown()
        _scheduler = None
