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


def path_map_candidates(
    samples: Sequence[str], folders: Iterable[str], root: str = OTHER_DOWNLOADS,
) -> list[PathMap]:
    """The ways the other program's folder can map onto VODLoft's, given sample paths and the folders VODLoft sees.

    the other program's ``root`` is VODLoft's /downloads or one of its folders; or
    VODLoft's /downloads is one of the other program's folders.
    """
    root = root.rstrip("/") or "/"
    candidates: list[PathMap] = [(root, "/downloads")]
    candidates += [(root, folder.rstrip("/")) for folder in sorted(set(folders))
                   if folder.startswith("/downloads/")]
    root_parts = PurePosixPath(root).parts
    inner: set[str] = set()
    for sample in samples:
        parts = PurePosixPath(sample).parts
        for depth in (1, 2):
            if len(parts) > len(root_parts) + depth and parts[:len(root_parts)] == root_parts:
                inner.add(str(PurePosixPath(*parts[:len(root_parts) + depth])))
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


def template_root(template: str, path_map: PathMap, root: str = OTHER_DOWNLOADS) -> tuple[str, str, str | None]:
    """A template written from the other program's ``root``, relative to the VODLoft folder for it, and that folder.

    The third value says why, when the template starts outside the mapped folder and so starts in /downloads/.
    """
    source, target = path_map
    if source == root:
        return template, target.rstrip("/") + "/", None
    try:
        inner = "/" + str(PurePosixPath(source).relative_to(root)) + "/"
    except ValueError:
        inner = None
    stripped = "/" + template.lstrip("/")
    if inner is not None and stripped.startswith(inner):
        return stripped[len(inner) - 1:], target.rstrip("/") + "/", None
    return template, "/downloads/", (
        f"The template starts outside {source}, which VODLoft can't see; new downloads go under /downloads/ instead"
    )
