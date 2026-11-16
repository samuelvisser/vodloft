"""ytdl-sub's download archive: every video a subscription downloaded, with the files it wrote.

ytdl-sub keeps one JSON file per subscription in its output folder, named
``.ytdl-sub-<subscription>-download-archive.json``, that maps each video id to its upload date,
its extractor, its playlist position and the files it wrote, relative to the output folder.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from yt_dlp.utils import sanitize_filename

MEDIA_EXTENSIONS = frozenset({
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".m4v", ".m4a", ".mp3", ".opus", ".ogg", ".oga", ".flac",
    ".wav", ".aac", ".mka",
})


@dataclass(frozen=True)
class ArchiveEntry:
    uid: str
    upload_date: str | None
    extractor: str | None
    file_names: tuple[str, ...]
    playlist_index: int | None = None

    @property
    def media_file(self) -> str | None:
        """The video or audio file the entry wrote; its thumbnail, NFO and info file are left out."""
        return next((name for name in self.file_names if PurePosixPath(name).suffix.lower() in MEDIA_EXTENSIONS), None)


def archive_names(subscription: str) -> tuple[str, ...]:
    """The archive's file name, as ytdl-sub names it now and, for names it changes, as it did before."""
    names = (f".ytdl-sub-{sanitize_filename(subscription)}-download-archive.json",
             f".ytdl-sub-{subscription}-download-archive.json")
    return tuple(dict.fromkeys(names))


def read_archive(path: Path) -> list[ArchiveEntry]:
    """The entries of an archive file; an unreadable file has none."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    if not isinstance(loaded, dict):
        return []
    entries = []
    for uid, mapping in loaded.items():
        if not isinstance(mapping, dict):
            continue
        index = mapping.get("playlist_index")
        entries.append(ArchiveEntry(
            uid=str(uid),
            upload_date=str(mapping["upload_date"]) if mapping.get("upload_date") else None,
            extractor=str(mapping["extractor"]) if mapping.get("extractor") else None,
            file_names=tuple(str(name) for name in mapping.get("file_names") or ()),
            playlist_index=int(index) if isinstance(index, int) else None,
        ))
    return entries
