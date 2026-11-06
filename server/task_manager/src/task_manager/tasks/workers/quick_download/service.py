from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from backend.utils.keyed_locks import KeyedLocks
from backend.db.core import run_write_transaction
from backend.services.quick_downloads import (
    QuickDownloadRefused,
    QuickDownloadRequest,
    prepare_quick_download_plan,
    quick_folder,
    ready_manifest,
)
from backend.services import quick_download_history as history
from config import get_settings
from downloader import DownloadCanceled, EncryptedMediaError, FileTooLargeError, SubscriptionRequiredError
from downloader.capacity import resources
from downloader.coordinator import execute_download_plan
from downloader.lifecycle import DownloadTracker
from downloader.storage.quick import remove_quick_folder, reserve_quick_folder, write_manifest
from downloader.transfer_context import transfer_context
from sources.pacing import RequestCanceled, request_context
from task_manager.scheduler.results import TaskResult
from task_manager.tasks.download_adapter import DownloadProgressReporter
from task_manager.tasks.media_download_operations import on_media_download_transfer_complete
from task_manager.tasks.quick_download_operations import mark_quick_download_started

logger = logging.getLogger(__name__)

_FOLDERS: KeyedLocks[str] = KeyedLocks()


@contextmanager
def _own_folder(quick_id: str, tracker: DownloadTracker) -> Iterator[Path]:
    """One attempt at a time per quick download: a restarted attempt waits for the
    canceled one to stop, then starts from an empty folder."""
    with _FOLDERS.hold(quick_id, while_waiting=tracker.ensure_active):
        folder = quick_folder(quick_id)
        remove_quick_folder(folder)
        reserve_quick_folder(get_settings().download_settings.quick_download_root, quick_id)
        yield folder


def _refused(request: QuickDownloadRequest, summary: str, reason: str) -> TaskResult:
    history.record_outcome(request.id, history.REFUSED, message=reason)
    return TaskResult(summary=summary, outcome="failed")


def run_quick_download(request_input: dict[str, Any], *, progress=None) -> TaskResult:
    """Fetch and convert one file into its quick download folder, then describe it in the manifest.

    Nothing is written to the database apart from the operation itself. A failed
    or canceled attempt leaves no folder behind.
    """
    request = QuickDownloadRequest.from_task_input(request_input)
    mark_quick_download_started()
    reporter = DownloadProgressReporter(progress)
    tracker = DownloadTracker(reporter, progress if callable(progress) else None)
    resources.media.configure(get_settings().download_settings.max_concurrent_downloads)
    execution = None
    ready = False
    folder: Path | None = None
    try:
        with tracker, _own_folder(request.id, tracker) as folder:
            def waiting(event):
                tracker.wait("prepare", event.reason if event else None, event.until if event else None)
            with request_context(observer=waiting, should_cancel=tracker.is_canceled), transfer_context(tracker.is_canceled, waiting):
                plan = prepare_quick_download_plan(request, folder, tracker)
            reporter.selected_format = plan.source.format_downloaded
            execution = execute_download_plan(
                plan, tracker=tracker, resources=resources,
                on_media_transfer_complete=on_media_download_transfer_complete,
            )
            tracker.ensure_active()
            lifecycle = tracker.finish()
            path = Path(execution.result.path)
            manifest = ready_manifest(request, path, execution.identity.size_bytes)
            write_manifest(folder, manifest)
            ready = True
        history.record_outcome(request.id, history.READY, size_bytes=manifest.size_bytes)
        _tell_owner(request)
        return TaskResult(
            summary=f"{request.title} is ready to download",
            data={
                "quick_download_id": request.id,
                "file_name": manifest.file_name,
                "size_bytes": manifest.size_bytes,
                "format": manifest.format,
                "format_downloaded": execution.format_downloaded,
                "expires_at": manifest.expires_at.isoformat(),
                "lifecycle": asdict(lifecycle),
            },
        )
    except BaseException as exc:
        tracker.cancel(user_requested=isinstance(exc, (DownloadCanceled, RequestCanceled)))
        tracker.stop_reporting()
        # Retrying cannot help with any of these.
        if isinstance(exc, EncryptedMediaError):
            return _refused(request, f"{request.title} is protected by DRM and cannot be downloaded", "Protected by DRM")
        if isinstance(exc, SubscriptionRequiredError):
            return _refused(request, f"{request.title} needs a subscription and cannot be downloaded", "Needs a subscription")
        if isinstance(exc, QuickDownloadRefused):
            return _refused(request, str(exc), str(exc))
        if isinstance(exc, FileTooLargeError):
            history.record_outcome(request.id, history.FAILED, message=str(exc))
            return TaskResult(summary=f"{request.title}: {exc}", outcome="failed")
        raise
    finally:
        if execution is not None:
            execution.cleanup_workspace()
        if not ready and folder is not None:
            remove_quick_folder(folder)


def _tell_owner(request) -> None:
    """Messages and actions: the person who asked for it may want to know it is ready."""
    from backend.services.notifications.emitters import quick_download_finished

    def work(session):
        quick_download_finished(session, owner=request.owner, title=request.title)

    try:
        run_write_transaction(work)
    except Exception:
        logger.exception("Could not record that quick download %s finished", request.id)
