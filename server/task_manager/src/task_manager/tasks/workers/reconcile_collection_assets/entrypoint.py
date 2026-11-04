from __future__ import annotations

import asyncio
from threading import Event

from downloader import DownloadCanceled

from backend.services.collection_assets import COLLECTION_ASSETS_REQUESTED
from task_manager.scheduler.registry import on_event, task

from .service import run_reconcile_collection_assets


@on_event(event_name=COLLECTION_ASSETS_REQUESTED, resource_type="collection")
@on_event(event_name="collection.indexed", resource_type="collection")
@on_event(event_name="collection.updated", resource_type="collection")
@on_event(event_name="download_profile.added", resource_type="download_profile")
@on_event(event_name="download_profile.updated", resource_type="download_profile")
@on_event(event_name="app.startup", resource_type="collection")
@task(
    key="reconcile_collection_assets",
    title="Reconcile collection artwork",
    description="Download and reconcile shared collection posters, backgrounds, square artwork and clear logos.",
    allowed_resource_types=("collection", "download_profile"),
    default_max_retries=3,
    tracks_progress=True,
)
async def reconcile_collection_assets(*, resource_id: int | None = None, resource_type: str | None = None, progress=None):
    stopped = Event()

    def check_canceled():
        if stopped.is_set() or (callable(progress) and progress()):
            raise DownloadCanceled("Collection artwork reconciliation was canceled")

    # Sessions are created in the worker thread, never transferred between threads.
    # Cancellation must also reach the thread before it can publish downloaded bytes.
    try:
        await asyncio.to_thread(
            run_reconcile_collection_assets, resource_id=resource_id, resource_type=resource_type,
            progress=progress, check_canceled=check_canceled,
        )
    finally:
        stopped.set()
