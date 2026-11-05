"""Remove the lock folders VODLoft used to keep in the download root.

The lock files that keep two tasks from changing the same collection artwork or
episode numbering at once now live in ``downloadSettings.lockRoot``, next to the
config file by default. The old ``.vodloft-assets-locks`` and
``.vodloft-index-locks`` folders in the download root are no longer used. Only
their ``.lock`` files are removed; a folder that holds anything else is left
where it is.

Revision ID: a3d91f5c07e2
Revises: c65c0a26c4e2
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from config import get_settings


revision = "a3d91f5c07e2"
down_revision = "c65c0a26c4e2"
title = "Remove the old lock folders from the download root"

logger = logging.getLogger(__name__)

_OLD_FOLDERS = (".vodloft-assets-locks", ".vodloft-index-locks")


def _remove_lock_folder(folder: Path) -> bool:
    if folder.is_symlink() or not folder.is_dir():
        return False
    for path in folder.iterdir():
        if path.suffix == ".lock" and path.is_file() and not path.is_symlink():
            path.unlink(missing_ok=True)
    try:
        folder.rmdir()
    except OSError:
        logger.warning("Left %s in place, because it holds more than lock files", folder)
        return False
    return True


def _remove_old_lock_folders(download_root: Path) -> int:
    return sum(_remove_lock_folder(download_root / name) for name in _OLD_FOLDERS)


async def migrate(context) -> None:
    download_root = Path(get_settings().download_settings.download_root)
    removed = await asyncio.to_thread(_remove_old_lock_folders, download_root)
    if removed:
        logger.info("Removed %s old lock folder(s) from %s", removed, download_root)
