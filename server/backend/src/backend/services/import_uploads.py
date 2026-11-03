"""Uploads of another program's config folder, kept privately for an importer.

An upload arrives in chunks of a few megabytes, so it gets through reverse
proxies that limit the size of one request, and resumes after a dropped
connection: the client asks how much of each file arrived and sends the rest.
Only the files the importer reads are taken (``importer.uploads``); the rest is
refused before it is sent. A finished upload replaces the previous one.

Everything lives under ``/config/imports/<importer>/``: ``incoming/`` while
an upload arrives, ``upload/`` once it is complete, and a ``work-…/`` folder
for each private copy of the database that an importer opens, so two reads
at the same time never share one.
"""
from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator

from config import get_settings
from importer.contract import Importer, ImportLocation
from importer.uploads import UploadFile, normalise_upload_path

CHUNK_LIMIT = 8 * 1024 * 1024
FILE_LIMIT = 64 * 1024 * 1024 * 1024
ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz", ".tar")
_ARCHIVE = "archive"
_FOLDER_DEPTH = 6
_FOLDER_SKIP = frozenset({"metadata", "logs", "cache", "tmp", "@eaDir", "#recycle"})


class UploadError(ValueError):
    """The upload can't be taken as it is."""


class UploadOffsetError(UploadError):
    """A chunk doesn't continue the file; ``received`` is where it should start."""

    def __init__(self, received: int) -> None:
        super().__init__(f"This file continues at byte {received}")
        self.received = received


@dataclass(frozen=True)
class AcceptedFile:
    path: str
    size: int
    secret: bool = False


def imports_root() -> Path:
    return get_settings().database_path.parent / "imports"


def _directory(importer: Importer) -> Path:
    return imports_root() / importer.key


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_archive(name: str) -> bool:
    return name.lower().endswith(ARCHIVE_SUFFIXES)


def begin_upload(importer: Importer, files: Iterable[tuple[str, int]], *, include_secrets: bool) -> dict[str, Any]:
    """Start an upload of these files (path in the picked folder, size); returns what will be taken."""
    accepted: dict[str, AcceptedFile] = {}
    sources: dict[str, str] = {}
    skipped: list[str] = []
    for path, size in files:
        if size < 0 or size > FILE_LIMIT:
            raise UploadError(f"{path} is too large to upload")
        if _is_archive(path) and not accepted and _ARCHIVE not in accepted:
            accepted[_ARCHIVE] = AcceptedFile(_ARCHIVE + _archive_suffix(path), size)
            sources[accepted[_ARCHIVE].path] = path
            continue
        found = normalise_upload_path(path, importer.upload_files)
        if found is None or (found[1].secret and not include_secrets):
            skipped.append(path)
            continue
        accepted[found[0]] = AcceptedFile(found[0], size, found[1].secret)
        sources[found[0]] = path
    if _ARCHIVE in accepted and len(accepted) > 1:
        raise UploadError("Upload an archive on its own, or the folder's files without one")
    if _ARCHIVE not in accepted and not any(
        rule.required and rule.pattern in accepted for rule in importer.upload_files
    ):
        raise UploadError(f"This is not a {importer.name} config folder: {importer.database} is missing")

    directory = _directory(importer)
    shutil.rmtree(directory / "incoming", ignore_errors=True)
    (directory / "incoming").mkdir(parents=True)
    _write_json(directory / "incoming.json", {
        "started_at": _now(), "include_secrets": include_secrets,
        "files": [{"path": item.path, "size": item.size, "secret": item.secret} for item in accepted.values()],
    })
    send = [{"source": sources[item.path], "path": item.path} for item in accepted.values()]
    return upload_status(importer) | {"skipped": skipped, "send": send}


def _archive_suffix(name: str) -> str:
    lowered = name.lower()
    return next(suffix for suffix in ARCHIVE_SUFFIXES if lowered.endswith(suffix))


def _incoming(importer: Importer) -> tuple[Path, dict[str, Any]]:
    directory = _directory(importer)
    manifest = _read_json(directory / "incoming.json")
    if manifest is None or not (directory / "incoming").is_dir():
        raise UploadError("No upload is in progress; start it again")
    return directory / "incoming", manifest


def _incoming_file(directory: Path, manifest: dict[str, Any], path: str) -> tuple[Path, int]:
    entry = next((item for item in manifest["files"] if item["path"] == path), None)
    if entry is None:
        raise UploadError(f"{path} is not part of this upload")
    return directory / PurePosixPath(path), int(entry["size"])


def write_chunk(importer: Importer, path: str, offset: int, data: bytes) -> int:
    """Append ``data`` at ``offset`` to an incoming file; returns how much of it has arrived."""
    if len(data) > CHUNK_LIMIT:
        raise UploadError(f"A chunk can be at most {CHUNK_LIMIT // (1024 * 1024)} MB")
    directory, manifest = _incoming(importer)
    target, size = _incoming_file(directory, manifest, path)
    received = target.stat().st_size if target.is_file() else 0
    if offset != received:
        raise UploadOffsetError(received)
    if received + len(data) > size:
        raise UploadError(f"{path} is larger than announced")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("ab") as file:
        file.write(data)
    return received + len(data)


def _extract(importer: Importer, archive: Path, into: Path, *, include_secrets: bool) -> list[str]:
    """Take only the importer's files out of an archive, never links or paths outside ``into``."""
    taken: list[str] = []

    def place(name: str, read) -> None:
        found = normalise_upload_path(name, importer.upload_files)
        if found is None or (found[1].secret and not include_secrets) or found[0] in taken:
            return
        target = into / PurePosixPath(found[0])
        target.parent.mkdir(parents=True, exist_ok=True)
        with read() as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination)
        taken.append(found[0])

    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                if not info.is_dir():
                    place(info.filename, lambda info=info: bundle.open(info))
    else:
        with tarfile.open(archive) as bundle:
            for member in bundle:
                if member.isfile():
                    place(member.name, lambda member=member: bundle.extractfile(member))
    return taken


def finish_upload(importer: Importer) -> dict[str, Any]:
    """Check that every file arrived, then make it the importer's upload."""
    directory, manifest = _incoming(importer)
    for entry in manifest["files"]:
        target, size = _incoming_file(directory, manifest, entry["path"])
        received = target.stat().st_size if target.is_file() else 0
        if received != size:
            raise UploadError(f"{entry['path']} has {received} of {size} bytes")
    archive = next((entry for entry in manifest["files"] if entry["path"].startswith(_ARCHIVE)), None)
    if archive is not None:
        source = directory / archive["path"]
        try:
            taken = _extract(importer, source, directory, include_secrets=bool(manifest.get("include_secrets")))
        except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as exc:
            raise UploadError(f"The archive can't be read: {exc}") from exc
        source.unlink()
        secrets = {rule.pattern for rule in importer.upload_files if rule.secret}
        manifest["files"] = [
            {"path": path, "size": (directory / path).stat().st_size,
             "secret": any(PurePosixPath(path).match(pattern) for pattern in secrets)}
            for path in taken
        ]
    return _replace_upload(importer, directory, manifest["files"])


def _replace_upload(importer: Importer, incoming: Path, files: list[dict[str, Any]]) -> dict[str, Any]:
    if not (incoming / PurePosixPath(importer.database)).is_file():
        raise UploadError(f"This is not a {importer.name} config folder: {importer.database} is missing")
    directory = _directory(importer)
    shutil.rmtree(directory / "upload", ignore_errors=True)
    incoming.replace(directory / "upload")
    _write_json(directory / "upload.json", {"uploaded_at": _now(), "files": files})
    (directory / "incoming.json").unlink(missing_ok=True)
    return upload_status(importer)


def upload_from_folder(importer: Importer, folder: Path, *, include_secrets: bool) -> dict[str, Any]:
    """Take the importer's files from a folder VODLoft can already see, as an upload would."""
    if not folder.is_dir():
        raise UploadError(f"{folder} is not a folder")
    directory = _directory(importer)
    incoming = directory / "incoming"
    shutil.rmtree(incoming, ignore_errors=True)
    incoming.mkdir(parents=True)
    files: list[dict[str, Any]] = []
    for path in _walk(folder):
        relative = path.relative_to(folder).as_posix()
        found = normalise_upload_path(relative, importer.upload_files)
        if found is None or (found[1].secret and not include_secrets):
            continue
        target = incoming / PurePosixPath(found[0])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        files.append({"path": found[0], "size": target.stat().st_size, "secret": found[1].secret})
    return _replace_upload(importer, incoming, files)


def _walk(folder: Path, depth: int = 0) -> Iterable[Path]:
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.is_symlink():
            continue
        if entry.is_dir():
            if depth < _FOLDER_DEPTH and entry.name not in _FOLDER_SKIP:
                yield from _walk(entry, depth + 1)
        elif entry.is_file():
            yield entry


def upload_status(importer: Importer) -> dict[str, Any]:
    directory = _directory(importer)
    upload = _read_json(directory / "upload.json")
    if upload is not None and not (directory / "upload").is_dir():
        upload = None
    incoming = _read_json(directory / "incoming.json")
    incoming_files: list[dict[str, Any]] = []
    if incoming is not None:
        for entry in incoming["files"]:
            target = directory / "incoming" / PurePosixPath(entry["path"])
            incoming_files.append({**entry, "received": target.stat().st_size if target.is_file() else 0})
    return {
        "upload": upload,
        "incoming": {"started_at": incoming["started_at"], "files": incoming_files} if incoming else None,
    }


def uploaded_at(importer: Importer) -> datetime | None:
    upload = upload_status(importer)["upload"]
    return datetime.fromisoformat(upload["uploaded_at"]) if upload else None


def remove_upload(importer: Importer) -> None:
    shutil.rmtree(_directory(importer), ignore_errors=True)


def remove_secrets(importer: Importer) -> None:
    """Delete the uploaded sign-ins and keys once an import used them."""
    directory = _directory(importer)
    upload = _read_json(directory / "upload.json")
    if upload is None:
        return
    kept = []
    for entry in upload["files"]:
        if entry.get("secret"):
            (directory / "upload" / PurePosixPath(entry["path"])).unlink(missing_ok=True)
        else:
            kept.append(entry)
    _write_json(directory / "upload.json", {**upload, "files": kept})


@contextmanager
def work_location(importer: Importer, path_map: tuple[str, str]) -> Iterator[ImportLocation]:
    """A private copy of the uploaded database for the importer to open, removed afterwards."""
    directory = _directory(importer)
    upload = directory / "upload"
    database = upload / PurePosixPath(importer.database)
    if not database.is_file():
        raise UploadError(f"Upload {importer.name}'s config folder first")
    work = Path(tempfile.mkdtemp(prefix="work-", dir=directory))
    try:
        copy = work / database.name
        shutil.copyfile(database, copy)
        wal = database.with_name(database.name + "-wal")
        if wal.is_file() and wal.stat().st_size > 0:
            shutil.copyfile(wal, work / wal.name)
        extras = upload / PurePosixPath(importer.extras) if importer.extras else None
        yield ImportLocation(database=copy, extras=extras if extras is not None and extras.is_dir() else None,
                             path_map=path_map)
    finally:
        shutil.rmtree(work, ignore_errors=True)
