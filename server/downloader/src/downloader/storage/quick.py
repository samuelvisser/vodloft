"""Ready folders for quick downloads: files handed to a browser once, then deleted.

A quick download is fetched and converted like any other download, but its
destination is a folder of its own inside the temporary root, so publication is
a same-filesystem rename and no byte ever lands outside that root. A small
manifest next to the file describes it. This module knows nothing about the
database: the manifest alone says whether a folder holds a ready file and when
it expires, so ready files survive a restart and unfinished ones do not.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from ..errors import DownloadError
from .helpers import _path_is_within, _write_all

logger = logging.getLogger(__name__)

QUICK_DIRECTORY_NAME = ".vodloft-quick"
MANIFEST_NAME = "manifest.json"
_MANIFEST_VERSION = 1
_MAX_MANIFEST_BYTES = 64 * 1024
_ID = re.compile(r"^[0-9a-f]{32}$")

QuickState = Literal["ready", "delivered"]


class InsufficientSpaceError(DownloadError):
    """The temporary folder does not have room for this file and the space to keep free."""


@dataclass(frozen=True)
class QuickManifest:
    """What a ready folder holds. ``details`` carries the application's own facts."""

    id: str
    title: str
    file_name: str
    size_bytes: int
    format: str
    created_at: datetime
    expires_at: datetime
    state: QuickState = "ready"
    delivered_at: datetime | None = None
    owner: str | None = None
    """Who may download the file. Empty until VODLoft has users."""
    details: dict[str, str] = field(default_factory=dict)

    def expired(self, now: datetime) -> bool:
        return now >= self.expires_at

    def delivered(self, at: datetime, *, keep_for: timedelta) -> QuickManifest:
        """Every byte has been sent: keep the file a little longer so a failed save can be retried."""
        if self.state == "delivered":
            return self
        return replace(self, state="delivered", delivered_at=at, expires_at=min(self.expires_at, at + keep_for))

    def to_json(self) -> bytes:
        data = asdict(self)
        for key in ("created_at", "expires_at", "delivered_at"):
            if data[key] is not None:
                data[key] = data[key].isoformat()
        return json.dumps({"version": _MANIFEST_VERSION, **data}, sort_keys=True).encode("utf-8")

    @classmethod
    def from_json(cls, payload: bytes) -> QuickManifest | None:
        try:
            raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or raw.pop("version", None) != _MANIFEST_VERSION:
            return None
        try:
            for key in ("created_at", "expires_at", "delivered_at"):
                if raw.get(key) is not None:
                    raw[key] = _aware(datetime.fromisoformat(raw[key]))
            manifest = cls(**raw)
        except (TypeError, ValueError):
            return None
        if (
            not is_quick_download_id(manifest.id)
            or manifest.state not in ("ready", "delivered")
            or not _is_plain_name(manifest.file_name)
            or not isinstance(manifest.size_bytes, int) or manifest.size_bytes < 0
            or not isinstance(manifest.details, dict)
        ):
            return None
        return manifest


@dataclass(frozen=True)
class QuickFolder:
    """One quick download's folder: the file and its manifest, nothing else."""

    path: Path
    manifest: QuickManifest | None

    @property
    def id(self) -> str:
        return self.path.name

    @property
    def file(self) -> Path | None:
        return self.path / self.manifest.file_name if self.manifest is not None else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _is_plain_name(name: object) -> bool:
    return (
        isinstance(name, str) and bool(name) and name not in (".", "..", MANIFEST_NAME)
        and Path(name).name == name and "\\" not in name and "\0" not in name
    )


def new_quick_download_id() -> str:
    return uuid.uuid4().hex


def is_quick_download_id(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def quick_root(temporary_root: str | Path) -> Path:
    return Path(temporary_root) / QUICK_DIRECTORY_NAME


def is_within_quick_root(path: str | Path, temporary_root: str | Path) -> bool:
    return _path_is_within(Path(path), quick_root(temporary_root))


def quick_folder_path(temporary_root: str | Path, quick_id: str) -> Path:
    if not is_quick_download_id(quick_id):
        raise ValueError("Not a quick download id")
    return quick_root(temporary_root) / quick_id


def reserve_quick_folder(temporary_root: str | Path, quick_id: str) -> Path:
    """Create the empty folder a quick download publishes into."""
    folder = quick_folder_path(temporary_root, quick_id)
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.mkdir()
    return folder


def write_manifest(folder: Path, manifest: QuickManifest) -> None:
    """Replace the manifest atomically, so a reader never sees half of one."""
    if manifest.id != folder.name:
        raise ValueError("A manifest belongs to the folder named after its id")
    payload = manifest.to_json()
    if len(payload) > _MAX_MANIFEST_BYTES:
        raise DownloadError("The quick download manifest is too large")
    temporary = folder / f".{MANIFEST_NAME}.{uuid.uuid4().hex}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_all(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.replace(temporary, folder / MANIFEST_NAME)
    finally:
        temporary.unlink(missing_ok=True)


def read_manifest(folder: Path) -> QuickManifest | None:
    """The folder's manifest, or None when it has none VODLoft can trust."""
    try:
        with (folder / MANIFEST_NAME).open("rb") as handle:
            payload = handle.read(_MAX_MANIFEST_BYTES + 1)
    except OSError:
        return None
    if len(payload) > _MAX_MANIFEST_BYTES:
        return None
    manifest = QuickManifest.from_json(payload)
    if manifest is None or manifest.id != folder.name:
        return None
    return manifest


def open_quick_folder(temporary_root: str | Path, quick_id: str) -> QuickFolder | None:
    """A ready folder whose file is still there, or None."""
    try:
        folder = quick_folder_path(temporary_root, quick_id)
    except ValueError:
        return None
    if folder.is_symlink() or not folder.is_dir():
        return None
    manifest = read_manifest(folder)
    if manifest is None:
        return QuickFolder(folder, None)
    file = folder / manifest.file_name
    if file.is_symlink() or not file.is_file():
        return QuickFolder(folder, None)
    return QuickFolder(folder, manifest)


def list_quick_folders(temporary_root: str | Path) -> list[QuickFolder]:
    """Every quick download folder, with its manifest when it has a valid one."""
    root = quick_root(temporary_root)
    try:
        entries = sorted(root.iterdir())
    except FileNotFoundError:
        return []
    except OSError:
        logger.warning("Could not list the quick download folder '%s'", root, exc_info=True)
        return []
    folders = []
    for entry in entries:
        if not is_quick_download_id(entry.name) or entry.is_symlink() or not entry.is_dir():
            continue
        found = open_quick_folder(temporary_root, entry.name)
        if found is not None:
            folders.append(found)
    return folders


def remove_quick_folder(folder: Path) -> bool:
    """Delete one quick download folder and everything in it."""
    try:
        if folder.is_symlink() or not folder.is_dir():
            folder.unlink(missing_ok=True)
        else:
            shutil.rmtree(folder)
    except FileNotFoundError:
        return True
    except OSError:
        logger.warning("Could not remove quick download folder '%s'", folder, exc_info=True)
        return False
    return True


@dataclass(frozen=True)
class QuickSweep:
    expired: tuple[QuickManifest, ...] = ()
    """Ready files whose time was up, now deleted."""
    unfinished: tuple[str, ...] = ()
    """Folders without a ready file, now deleted."""


def sweep_quick_folders(
    temporary_root: str | Path,
    *,
    now: datetime | None = None,
    remove_unfinished: bool = False,
) -> QuickSweep:
    """Delete expired ready files and, when asked, folders that never became ready.

    Startup recovery passes ``remove_unfinished`` while nothing runs. The
    scheduled sweep does not, because an unfinished folder may belong to a
    download that is still working. Anything in the root that is not a quick
    download folder is left alone.
    """
    now = now or datetime.now(timezone.utc)
    root = quick_root(temporary_root)
    try:
        entries = sorted(root.iterdir())
    except FileNotFoundError:
        return QuickSweep()
    except OSError:
        logger.warning("Could not sweep the quick download folder '%s'", root, exc_info=True)
        return QuickSweep()
    expired: list[QuickManifest] = []
    unfinished: list[str] = []
    for entry in entries:
        if not is_quick_download_id(entry.name):
            continue
        if entry.is_symlink() or not entry.is_dir():
            continue
        found = open_quick_folder(temporary_root, entry.name)
        if found is None:
            continue
        if found.manifest is None:
            if remove_unfinished and remove_quick_folder(entry):
                unfinished.append(entry.name)
        elif found.manifest.expired(now) and remove_quick_folder(entry):
            expired.append(found.manifest)
    if unfinished:
        logger.info("Removed %s unfinished quick download(s)", len(unfinished))
    if expired:
        logger.info("Deleted %s expired quick download file(s)", len(expired))
    return QuickSweep(tuple(expired), tuple(unfinished))


def ensure_free_space(temporary_root: str | Path, *, expected_bytes: int | None, keep_free_bytes: int) -> None:
    """Refuse to start when the file would leave less than ``keep_free_bytes`` free."""
    path = Path(temporary_root)
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        logger.warning("Could not check free space in '%s'", temporary_root, exc_info=True)
        return
    needed = keep_free_bytes + (expected_bytes or 0)
    if free < needed:
        raise InsufficientSpaceError(
            f"The temporary folder has {_size(free)} free, and this download needs {_size(needed)} "
            f"({_size(expected_bytes or 0)} for the file and {_size(keep_free_bytes)} to keep free)"
        )


def _size(value: float) -> str:
    if value < 1024:
        return f"{value:.0f} bytes"
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
    raise AssertionError("unreachable")
