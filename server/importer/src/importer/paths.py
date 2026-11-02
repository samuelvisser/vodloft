"""Where the other program's files are, as VODLoft sees them.

The other program names its files by the folder it saw, such as Pinchflat's
``/downloads``. VODLoft sees the same files under its own ``/downloads/``,
often at another depth. A path map pairs the two folders; it is found from
sample files and can be changed by the person.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import PurePosixPath

OTHER_DOWNLOADS = "/downloads"
"""The download folder of the other program, inside its container."""

PathMap = tuple[str, str]
"""A folder as the other program sees it, and the same folder as VODLoft sees it."""
DEFAULT_PATH_MAP: PathMap = ("/downloads", "/downloads")


def map_path(path: str | None, path_map: PathMap = DEFAULT_PATH_MAP) -> str | None:
    """The other program's path as the ``/downloads/…`` path VODLoft sees, or None when it is outside the mapped folder."""
    if not path:
        return None
    source, target = path_map
    try:
        relative = PurePosixPath(path).relative_to(source)
    except ValueError:
        return None
    if ".." in relative.parts:
        return None
    return str(PurePosixPath(target) / relative)


def path_map_candidates(samples: Sequence[str], folders: Iterable[str]) -> list[PathMap]:
    """The ways the other program's folder can map onto VODLoft's, given sample paths and the folders VODLoft sees.

    the other program's /downloads is VODLoft's /downloads or one of its folders; or
    VODLoft's /downloads is one of the other program's folders.
    """
    candidates: list[PathMap] = [DEFAULT_PATH_MAP]
    candidates += [(OTHER_DOWNLOADS, folder.rstrip("/")) for folder in sorted(set(folders))
                   if folder.startswith("/downloads/")]
    inner: set[str] = set()
    for sample in samples:
        parts = PurePosixPath(sample).parts
        for depth in (1, 2):
            if len(parts) > 2 + depth and parts[:2] == ("/", "downloads"):
                inner.add(str(PurePosixPath(*parts[:2 + depth])))
    candidates += [(folder, "/downloads") for folder in sorted(inner)]
    return candidates


def detect_path_map(
    samples: Sequence[str], exists: Callable[[str], bool], candidates: Sequence[PathMap],
) -> tuple[PathMap, int]:
    """The candidate under which most sample files exist, and how many do; the first wins a tie."""
    best, best_found = DEFAULT_PATH_MAP, -1
    for candidate in candidates:
        found = sum(1 for sample in samples if (mapped := map_path(sample, candidate)) and exists(mapped))
        if found > best_found:
            best, best_found = candidate, found
    return best, max(best_found, 0)
