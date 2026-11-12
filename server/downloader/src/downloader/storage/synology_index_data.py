"""Remove the ``@eaDir`` folder that a Synology NAS leaves in a folder VODLoft's files have left.

DSM keeps what it knows about the files of a folder (thumbnails, media information, extended
attributes) in a hidden ``@eaDir`` folder beside them. When the files move away that data is left
behind, and the folder never becomes empty. This is the only place where the cleanup of emptied
folders deletes files, so it accepts exactly what DSM writes and nothing else:

- the folder holds ``@eaDir`` and nothing else at all;
- ``@eaDir`` is a real folder on the same filesystem, not a symbolic link or a mount;
- it holds only files DSM names (``SYNO…``, ``…@SynoEAStream``, ``…@SynoResource``) and one level of
  folders, one per media file, that again hold only ``SYNO…`` files.

Everything is checked before anything is deleted. One entry that does not fit, such as a file with
another name, a link, or a folder one level deeper, and nothing is removed. Entries are reached
through the opened folders rather than by path, so a folder swapped for a link in the meantime is
not followed.
"""
from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

INDEX_FOLDER = "@eaDir"
_FILE_PREFIX = "SYNO"
_FILE_SUFFIXES = ("@SynoEAStream", "@SynoResource")
_OPEN_FOLDER = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_SUPPORTED = (
    hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW")
    and {os.open, os.stat, os.unlink, os.rmdir} <= os.supports_dir_fd
    and os.listdir in os.supports_fd
)


def remove_synology_index_data(folder: Path) -> bool:
    """Remove ``folder/@eaDir`` when the folder holds nothing else and it holds only DSM's own data."""
    if not _SUPPORTED:
        return False
    try:
        parent = os.open(folder, _OPEN_FOLDER)
    except OSError:
        return False
    try:
        if os.listdir(parent) != [INDEX_FOLDER]:
            return False
        try:
            index = os.open(INDEX_FOLDER, _OPEN_FOLDER, dir_fd=parent)
        except OSError:
            return False
        try:
            device = os.fstat(parent).st_dev
            if os.fstat(index).st_dev != device or not _only_index_data(index, device, top=True):
                return False
            _delete_index_data(index, device, top=True)
        finally:
            os.close(index)
        os.rmdir(INDEX_FOLDER, dir_fd=parent)
    except OSError:
        logger.warning("Could not remove the Synology index data in %s", folder, exc_info=True)
        return False
    finally:
        os.close(parent)
    logger.info("Removed the Synology index data left in %s", folder)
    return True


def _is_index_file(name: str, *, top: bool) -> bool:
    return name.startswith(_FILE_PREFIX) or (top and name.endswith(_FILE_SUFFIXES))


def _only_index_data(folder: int, device: int, *, top: bool) -> bool:
    """Whether the opened folder holds only what DSM writes there. Nothing is changed."""
    for name in os.listdir(folder):
        status = os.stat(name, dir_fd=folder, follow_symlinks=False)
        if status.st_dev != device:
            return False
        if stat.S_ISREG(status.st_mode):
            if not _is_index_file(name, top=top):
                return False
        elif stat.S_ISDIR(status.st_mode) and top:
            try:
                child = os.open(name, _OPEN_FOLDER, dir_fd=folder)
            except OSError:
                return False
            try:
                if os.fstat(child).st_dev != device or not _only_index_data(child, device, top=False):
                    return False
            finally:
                os.close(child)
        else:
            return False
    return True


def _delete_index_data(folder: int, device: int, *, top: bool) -> None:
    """Delete what ``_only_index_data`` accepted, checking each entry again; anything else raises."""
    for name in os.listdir(folder):
        status = os.stat(name, dir_fd=folder, follow_symlinks=False)
        if status.st_dev != device:
            raise OSError(f"{name} is on another filesystem")
        if stat.S_ISREG(status.st_mode) and _is_index_file(name, top=top):
            os.unlink(name, dir_fd=folder)
        elif stat.S_ISDIR(status.st_mode) and top:
            child = os.open(name, _OPEN_FOLDER, dir_fd=folder)
            try:
                if os.fstat(child).st_dev != device:
                    raise OSError(f"{name} is on another filesystem")
                _delete_index_data(child, device, top=False)
            finally:
                os.close(child)
            os.rmdir(name, dir_fd=folder)
        else:
            raise OSError(f"{name} is not Synology index data")
