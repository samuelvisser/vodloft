"""Paths as a media server sees them, which may be a Windows server with drive letters and backslashes."""
from __future__ import annotations

import re
from typing import Any

_WINDOWS = re.compile(r"^(?:[A-Za-z]:|\\\\)")


def _windows(path: str) -> bool:
    """A drive letter (``W:\\``) or a network share (``\\\\nas\\media``)."""
    return bool(_WINDOWS.match(path)) or ("\\" in path and "/" not in path)


def _parts(path: str) -> list[str]:
    return [part for part in re.split(r"[\\/]+", path) if part]


def _inside(path: str, folder: str) -> list[str] | None:
    """What follows ``folder`` in ``path``, part by part, or None when the path is elsewhere."""
    windows = _windows(folder)
    path_parts, folder_parts = _parts(path), _parts(folder)
    if windows:
        path_parts, folder_parts = [part.casefold() for part in path_parts], [part.casefold() for part in folder_parts]
    if path_parts[:len(folder_parts)] != folder_parts:
        return None
    if not windows and path.startswith("/") != folder.startswith("/"):
        return None
    return _parts(path)[len(folder_parts):]


def mapped_path(path: str, config: dict[str, Any]) -> str:
    """The path as the media server sees it: the part under ``path_from`` moved to ``path_to``, written with the
    server's own separator. A path outside ``path_from`` stays as it is."""
    source, target = str(config.get("path_from") or "").strip(), str(config.get("path_to") or "").strip()
    if not source or not target:
        return path
    rest = _inside(path, source)
    if rest is None:
        return path
    separator = "\\" if _windows(target) else "/"
    base = target.rstrip("\\/")
    if not rest:
        return base + separator if base.endswith(":") or not base else base
    return base + separator + separator.join(rest)


def holds(location: str, path: str) -> bool:
    """Whether a media server's library folder ``location`` holds ``path``, both as the server sees them."""
    return bool(location.strip()) and _inside(path, location) is not None
