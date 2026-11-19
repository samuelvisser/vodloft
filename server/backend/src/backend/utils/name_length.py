"""File and folder names short enough for the filesystem.

Linux, macOS and Windows refuse a single file or folder name longer than 255 bytes, whatever the
length of the whole path. A long title, with emoji or another script that takes several bytes per
letter, can reach that on its own. VODLoft also writes names that are longer than the media file's:
``Episode.en.auto.default.srt``, ``Episode.nfo`` and the ``.part`` files it writes them through.

A file's name, without its extension, therefore keeps ``SIDECAR_RESERVE_BYTES`` free for those
endings, and a folder's name keeps to the limit itself. When a name is too long, the values the
template filled in are shortened from their end, longest first, so text typed in the template, such
as `` [{{ episode_site_id }}]`` around a value or a season folder's name, stays as it is. Only when
the values alone can't make room is the end of the name cut.

A name that already fits never changes.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

MAX_NAME_BYTES = 255
"""The longest file or folder name, in bytes, that Linux, macOS and Windows filesystems accept."""

SIDECAR_RESERVE_BYTES = 30
"""What a file's name leaves free after its stem, for the longest ending VODLoft adds to it.

Such as ``.en.auto.default.srt.part`` (25 bytes) or ``.mp4.metadata.part`` (18 bytes).
"""

_TRIMMED_END = " .-_,;"
"""Left at the end of a shortened value, these would read as a broken word: they go too."""


@dataclass
class _Names:
    filled: list[str] = field(default_factory=list)
    shortened: list[str] = field(default_factory=list)


_NAMES: ContextVar[_Names | None] = ContextVar("vodloft_output_names", default=None)


@contextmanager
def tracking_output_names() -> Iterator[_Names]:
    """Note the values a template fills in while it renders, so a long name shortens those first."""
    names = _Names()
    token = _NAMES.set(names)
    try:
        yield names
    finally:
        _NAMES.reset(token)


def note_filled_value(text: str) -> None:
    """Remember one value a template filled in, while :func:`tracking_output_names` is on."""
    names = _NAMES.get()
    if names is not None and text:
        names.filled.append(text)


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


def _cut(text: str, size: int) -> str:
    """``text`` cut to at most ``size`` bytes, never inside a letter."""
    return text.encode("utf-8")[:max(size, 0)].decode("utf-8", errors="ignore")


def fit_name(name: str, *, extension: str | None = None) -> str:
    """``name``, shortened when it is too long for the filesystem.

    ``extension`` marks a file name: its extension is kept, and the name leaves room for the
    endings of the files VODLoft writes beside it.
    """
    stem, suffix = name, ""
    if extension and name.endswith(f".{extension}"):
        stem, suffix = name[: -len(extension) - 1], f".{extension}"
        limit = MAX_NAME_BYTES - SIDECAR_RESERVE_BYTES
    else:
        limit = MAX_NAME_BYTES
    if _size(stem) <= limit:
        return name

    names = _NAMES.get()
    filled = sorted({text for text in (names.filled if names else ()) if text in stem}, key=_size, reverse=True)
    fitted = stem
    for value in filled:
        overflow = _size(fitted) - limit
        if overflow <= 0:
            break
        if value not in fitted:
            continue
        shorter = _cut(value, _size(value) - overflow).rstrip(_TRIMMED_END)
        fitted = fitted.replace(value, shorter, 1)
    if _size(fitted) > limit:
        fitted = _cut(fitted, limit).rstrip(_TRIMMED_END)
    fitted = f"{fitted or '_'}{suffix}"
    if names is not None:
        names.shortened.append(name)
    return fitted
