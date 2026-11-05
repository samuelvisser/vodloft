"""Move the lock files and thumbnails VODLoft kept in the download root next to the config file.

The lock files that keep two tasks from changing the same collection artwork or
episode numbering at once now live in ``downloadSettings.lockRoot``, and the
thumbnails VODLoft makes itself in ``downloadSettings.thumbnailRoot``. Both sit
next to the config file by default.

The old ``.vodloft-assets-locks`` and ``.vodloft-index-locks`` folders in the
download root are no longer used, so their ``.lock`` files are removed. The
thumbnails in the old ``.vodloft-thumbnails`` folder move to the thumbnail
folder, unless that is still the old folder. A folder that keeps anything else
is left where it is.

Revision ID: a3d91f5c07e2
Revises: c65c0a26c4e2
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from config import get_settings


revision = "a3d91f5c07e2"
down_revision = "c65c0a26c4e2"
title = "Move lock files and thumbnails out of the download root"

logger = logging.getLogger(__name__)

_OLD_LOCK_FOLDERS = (".vodloft-assets-locks", ".vodloft-index-locks")
_OLD_THUMBNAIL_FOLDER = ".vodloft-thumbnails"


def _remove_if_empty(folder: Path) -> bool:
    try:
        folder.rmdir()
    except OSError:
        logger.warning("Left %s in place, because it still holds files", folder)
        return False
    return True


def _remove_lock_folder(folder: Path) -> bool:
    if folder.is_symlink() or not folder.is_dir():
        return False
    for path in folder.iterdir():
        if path.suffix == ".lock" and path.is_file() and not path.is_symlink():
            path.unlink(missing_ok=True)
    return _remove_if_empty(folder)


def _move_thumbnails(folder: Path, thumbnail_root: Path) -> bool:
    if folder.is_symlink() or not folder.is_dir():
        return False
    if folder.resolve() == thumbnail_root.resolve():
        return False
    thumbnail_root.mkdir(parents=True, exist_ok=True)
    for path in folder.iterdir():
        target = thumbnail_root / path.name
        if not path.is_file() or path.is_symlink():
            continue
        if target.exists():
            # The new folder already has this thumbnail.
            path.unlink()
        else:
            shutil.move(path, target)
    return _remove_if_empty(folder)


def _move_out_of_download_root(download_root: Path, thumbnail_root: Path) -> int:
    moved = sum(_remove_lock_folder(download_root / name) for name in _OLD_LOCK_FOLDERS)
    return moved + _move_thumbnails(download_root / _OLD_THUMBNAIL_FOLDER, thumbnail_root)


async def migrate(context) -> None:
    download_settings = get_settings().download_settings
    download_root = Path(download_settings.download_root)
    done = await asyncio.to_thread(
        _move_out_of_download_root, download_root, Path(download_settings.thumbnail_root),
    )
    if done:
        logger.info("Moved %s VODLoft folder(s) out of %s", done, download_root)
