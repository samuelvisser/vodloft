"""The yt-dlp metadata Pinchflat saved for each downloaded video, for the template values it holds.

Pinchflat keeps the whole ``--dump-json`` of a video in its config folder, as
``/config/metadata/media_items/<id>/metadata.json.gz``. VODLoft learns the same
values, such as the uploader, only when it indexes a Collection; reading them
here lets the import preview render a template the way VODLoft will.
"""
from __future__ import annotations

import gzip
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path, PurePosixPath

_CONFIG = PurePosixPath("/config")


def saved_values(folder: Path | None, files: Mapping[int, str]) -> dict[int, dict[str, str]]:
    """The template values of each media item whose metadata the upload has, by item id."""
    if folder is None:
        return {}
    values: dict[int, dict[str, str]] = {}
    for item_id, saved in files.items():
        try:
            relative = PurePosixPath(saved).relative_to(_CONFIG)
        except ValueError:
            continue
        path = folder / relative
        try:
            stat = path.stat()
        except OSError:
            continue
        found = _read(str(path), stat.st_mtime_ns, stat.st_size)
        if found:
            values[item_id] = dict(found)
    return values


@lru_cache(maxsize=None)
def _read(path: str, _mtime_ns: int, _size: int) -> tuple[tuple[str, str], ...]:
    """The values in one metadata file; cached, as a preview reads every file again each time."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            info = json.load(handle)
    except (OSError, ValueError, EOFError):
        return ()
    if not isinstance(info, dict):
        return ()
    values: dict[str, str] = {}
    # The same as VODLoft's index takes for an episode's uploader.
    uploader = info.get("uploader") or info.get("channel")
    if isinstance(uploader, str) and uploader:
        values["episode_uploader"] = uploader
    duration = info.get("duration")
    if isinstance(duration, (int, float)):
        values["duration_seconds"] = str(round(duration))
    return tuple(values.items())
