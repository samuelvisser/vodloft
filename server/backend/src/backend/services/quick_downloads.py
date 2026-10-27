"""Quick downloads: files fetched for one browser download, never part of the library.

A quick download has no media row and no MediaDownload. While it runs it is a
TaskOperation; once ready, the manifest in its folder inside the temporary root
describes it. Nothing here is read by the file watcher or by verification.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from config import get_settings
from downloader.storage.quick import QuickSweep, sweep_quick_folders

logger = logging.getLogger(__name__)


def sweep_quick_downloads(
    temporary_root: str | Path | None = None, *, remove_unfinished: bool = False, now: datetime | None = None,
) -> QuickSweep:
    """Delete quick download files whose time is up.

    Startup recovery also removes folders that never became ready, because no
    quick download can still be running then.
    """
    return sweep_quick_folders(
        temporary_root or get_settings().download_settings.temporary_download_root, now=now or datetime.now(timezone.utc), remove_unfinished=remove_unfinished,
    )


def run_scheduled_quick_download_sweep() -> None:
    """The once-a-minute housekeeping job; it must never take the scheduler down."""
    try:
        sweep_quick_downloads()
    except Exception:
        logger.exception("Could not sweep expired quick downloads")
