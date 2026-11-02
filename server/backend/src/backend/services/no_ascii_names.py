"""Numbered ``no_ascii_file_name`` files, so two of them never share a name.

A Restricted name with nothing ASCII left becomes ``no_ascii_file_name``. The
first download in a folder keeps that name; the next ones become
``no_ascii_file_name_2``, ``_3``... The number is chosen when the download's
file name is first worked out and stays with its stored path afterwards, so
it never shifts when another such episode appears.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from backend.db.models.media_download import MediaDownloadBase
from backend.utils.filenames import NO_ASCII_FILE_NAME, is_no_ascii_name, numbered_no_ascii_name


def settle_no_ascii_name(download: MediaDownloadBase, destination: Path, *, session: Session | None = None) -> Path:
    """The destination, numbered when it is a ``no_ascii_file_name`` another file already has."""
    if not is_no_ascii_name(destination.name):
        return destination
    current = Path(download.file_path) if download.file_path else None
    if (
        current is not None
        and current.parent == destination.parent
        and current.suffix == destination.suffix
        and is_no_ascii_name(current.name)
    ):
        return current

    session = session or object_session(download)
    escaped = str(destination.parent / NO_ASCII_FILE_NAME).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    taken = set(session.scalars(
        select(MediaDownloadBase.file_path).where(
            MediaDownloadBase.id != download.id,
            MediaDownloadBase.file_path.like(f"{escaped}%", escape="\\"),
        )
    )) if session is not None else set()
    number = 1
    while True:
        candidate = destination.with_name(numbered_no_ascii_name(destination.name, number))
        if str(candidate) not in taken and not candidate.exists():
            return candidate
        number += 1
