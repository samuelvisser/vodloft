"""The info file ytdl-sub saves beside each video, for the template values it holds.

ytdl-sub writes yt-dlp's ``.info.json`` next to every video it downloads, and its download archive lists it with the
video's other files. The archive itself keeps no titles; VODLoft learns them, and values such as the uploader, only
when it indexes a Collection. Reading them here lets the import preview render a template the way VODLoft will.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


def info_values(path: Path) -> dict[str, str]:
    """The template values in one info file; nothing when it can't be read."""
    try:
        stat = path.stat()
    except OSError:
        return {}
    return dict(_read(str(path), stat.st_mtime_ns, stat.st_size))


@lru_cache(maxsize=4096)
def _read(path: str, _mtime_ns: int, _size: int) -> tuple[tuple[str, str], ...]:
    """Cached, as a preview reads every file again each time."""
    try:
        with open(path, encoding="utf-8") as handle:
            info = json.load(handle)
    except (OSError, ValueError):
        return ()
    if not isinstance(info, dict):
        return ()
    values: dict[str, str] = {}
    title = info.get("title")
    if isinstance(title, str) and title:
        values["title"] = title
    # The same as VODLoft's index takes for an episode's uploader.
    uploader = info.get("uploader") or info.get("channel")
    if isinstance(uploader, str) and uploader:
        values["episode_uploader"] = uploader
    duration = info.get("duration")
    if isinstance(duration, (int, float)):
        values["duration_seconds"] = str(round(duration))
    return tuple(values.items())
