"""Remove the folders that moving managed files away left empty.

Deleting a folder that still holds something of the user's must be impossible, not merely unlikely, so
every rule below holds on its own:

- A folder is only ever removed with ``os.rmdir``, which the operating system refuses for a folder that
  holds anything at all: a hidden file, a symbolic link, another folder. Nothing here deletes a file or
  walks into a folder, and nothing may be added that does.
- The one thing that may be cleared out of a folder first is the ``@eaDir`` index data a Synology NAS
  left there, under the rules of ``synology_index_data``, which lives apart so those rules stay in one place.
- Only the folders the caller names are tried, and from each one its parents in turn, stopping at the
  first folder that cannot be removed.
- The root is never removed and nothing outside it is touched. A folder reached through a symbolic link
  counts as outside it.
- A folder that is, or that holds, one of the ``keep`` paths stays, also when it is empty.
"""
from __future__ import annotations

import errno
import logging
import os
import stat
from collections.abc import Iterable
from pathlib import Path

from .synology_index_data import remove_synology_index_data

logger = logging.getLogger(__name__)


def remove_emptied_folders(folders: Iterable[Path], *, root: Path, keep: Iterable[Path] = ()) -> list[Path]:
    """Remove each given folder that is empty, then each parent this leaves empty. Return what was removed.

    ``folders`` are the folders managed files were just moved out of or deleted from. ``root`` is the
    download root. ``keep`` are paths whose folders must stay, such as where the files went.
    """
    root = Path(root)
    real_root = Path(os.path.realpath(root))
    if not root.is_absolute() or real_root != root or real_root.parent == real_root or not real_root.is_dir():
        # Without a plain, existing root that is not the filesystem's own there is no boundary to trust.
        return []
    kept = {real_root}
    for path in keep:
        real = Path(os.path.realpath(path))
        kept.add(real)
        kept.update(real.parents)

    removed: list[Path] = []
    for folder in sorted({Path(folder) for folder in folders}, key=lambda path: len(path.parts), reverse=True):
        while _may_try(folder, real_root, kept):
            try:
                os.rmdir(folder)
            except OSError as error:
                # Not empty, in use, or not ours to remove: it stays, and so do its parents. The one
                # exception is a folder that holds nothing but the index data of a Synology NAS.
                if error.errno not in (errno.ENOTEMPTY, errno.EEXIST) or not remove_synology_index_data(folder):
                    break
                try:
                    os.rmdir(folder)
                except OSError:
                    break
            removed.append(folder)
            folder = folder.parent
    if removed:
        logger.info("Removed %d folder(s) left empty: %s", len(removed), ", ".join(map(str, removed)))
    return removed


def _may_try(folder: Path, root: Path, kept: set[Path]) -> bool:
    """Whether ``os.rmdir`` may be tried on this folder; ``os.rmdir`` itself still refuses a folder with contents."""
    if not folder.is_absolute() or ".." in folder.parts:
        return False
    if folder == root or not folder.is_relative_to(root):
        return False
    if folder in kept:
        return False
    try:
        if not stat.S_ISDIR(os.lstat(folder).st_mode):
            return False
    except OSError:
        return False
    # A symbolic link anywhere on the way could lead out of the root.
    if Path(os.path.realpath(folder)) != folder:
        return False
    return not os.path.ismount(folder)
