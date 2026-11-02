"""Finding the media files in a folder, and the sidecars next to each."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

VIDEO_EXTENSIONS = frozenset({"mp4", "m4v", "mkv", "webm", "mov", "avi", "ts", "flv", "wmv", "mpg", "mpeg", "3gp"})
AUDIO_EXTENSIONS = frozenset({"m4a", "mp3", "opus", "ogg", "oga", "aac", "flac", "wav", "wma", "mka"})
HLS_EXTENSIONS = frozenset({"m3u8"})
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | HLS_EXTENSIONS
# Downloads that never finished, yt-dlp's and VODLoft's own working files.
_PARTIAL_SUFFIXES = (".part", ".ytdl", ".temp", ".tmp", ".rawts", ".crdownload")
_SKIPPED_PREFIXES = (".vodloft-", ".wireloft-", "._")
_FORMAT_PART = __import__("re").compile(r"\.f\d+$")


@dataclass(frozen=True)
class FoundFile:
    path: str
    """Relative to the scanned folder, with ``/`` between folders."""
    size: int
    sidecars: tuple[str, ...] = ()
    """Names of the files next to it that start with its name, such as ``Name.info.json``."""

    @property
    def stem(self) -> str:
        name = self.path.rsplit("/", 1)[-1]
        return name.rsplit(".", 1)[0] if "." in name else name

    @property
    def extension(self) -> str:
        name = self.path.rsplit("/", 1)[-1]
        return name.rsplit(".", 1)[1].lower() if "." in name else ""


def is_media_file(name: str, *, include_hls: bool = True) -> bool:
    lowered = name.lower()
    if lowered.startswith(_SKIPPED_PREFIXES) or lowered.endswith(_PARTIAL_SUFFIXES):
        return False
    if "." not in lowered:
        return False
    stem, extension = lowered.rsplit(".", 1)
    if extension in HLS_EXTENSIONS and not include_hls:
        return False
    # yt-dlp's per-format parts before merging, such as Name.f137.mp4.
    return extension in MEDIA_EXTENSIONS and not _FORMAT_PART.search(stem)


def scan_folder(root: Path, *, include_hls: bool = True, limit: int = 100_000) -> list[FoundFile]:
    """Every media file under ``root``, in name order. Hidden folders are skipped."""
    found: list[FoundFile] = []
    for directory, folders, names in os.walk(root):
        folders[:] = sorted(
            name for name in folders
            if not name.startswith(".") and not name.lower().endswith(_PARTIAL_SUFFIXES)
        )
        names = sorted(names)
        relative = Path(directory).relative_to(root).as_posix()
        prefix = "" if relative == "." else f"{relative}/"
        for name in names:
            if not is_media_file(name, include_hls=include_hls):
                continue
            path = Path(directory) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            if not path.is_file():
                continue
            stem = name.rsplit(".", 1)[0]
            sidecars = tuple(
                other for other in names
                if other != name and other.startswith(f"{stem}.") and not is_media_file(other)
            )
            found.append(FoundFile(f"{prefix}{name}", stat.st_size, sidecars))
            if len(found) >= limit:
                return found
    return found
