"""Taking files already on disk into VODLoft, as if VODLoft had downloaded them.

Every importer and the existing-files matcher adopt through :func:`adopt`.
:func:`find_file` first reads the file's identity and the sidecars VODLoft
recognises next to it, outside any write transaction; :func:`adopt` then
records the download as available and writes an "Imported" history entry.
Files are never moved or changed.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import (
    DownloadProfile,
    Episode,
    EpisodeMediaDownload,
    LocalMediaProfileBase,
    MediaDownloadBase,
    MediaItemBase,
    Movie,
    MovieExtra,
    MovieExtraMediaDownload,
    MovieMediaDownload,
    Video,
    VideoMediaDownload,
)
from backend.db.models.media_download.MediaDownloadAsset import MediaDownloadAsset
from backend.services.media_download_history import record_media_download_history
from backend.services.sites import collection_site
from backend.services.upgrade_check import schedule_imported_upgrade_check
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.media_download_history_types import MediaDownloadHistoryAction
from backend.types.media_types import MediaType
from config import get_settings
from downloader.storage.identity import ArtifactIdentity, inspect_artifact

DOWNLOADS_PREFIX = "/downloads/"
_THUMBNAIL_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
_SUBTITLE = re.compile(r"^\.(?:(?P<language>[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*)\.)?(?P<forced>forced\.)?(?:default\.)?(?:srt|vtt)$")


class AdoptionError(ValueError):
    """The file can't be adopted; the message says why."""


@dataclass(frozen=True)
class FoundAsset:
    asset_key: str
    kind: str
    path: Path
    identity: ArtifactIdentity


@dataclass(frozen=True)
class FoundFile:
    """A file on disk as :func:`find_file` read it, ready to adopt."""

    path: Path
    identity: ArtifactIdentity
    modified_at: datetime
    assets: tuple[FoundAsset, ...]


@dataclass(frozen=True)
class Adopted:
    download: MediaDownloadBase
    created: bool


def download_root() -> Path:
    return Path(get_settings().download_settings.download_root).resolve()


def real_path(virtual: str) -> Path:
    """A ``/downloads/…`` path as the file inside the download folder; refused when it is outside."""
    if not virtual.startswith(DOWNLOADS_PREFIX) and virtual != DOWNLOADS_PREFIX.rstrip("/"):
        raise AdoptionError(f"{virtual} is not inside /downloads/")
    root = download_root()
    path = (root / virtual[len(DOWNLOADS_PREFIX):]).resolve()
    if path != root and not path.is_relative_to(root):
        raise AdoptionError(f"{virtual} is outside the download folder")
    return path


def virtual_path(path: Path) -> str:
    root = download_root()
    resolved = path.resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise AdoptionError(f"{path} is outside the download folder")
    relative = resolved.relative_to(root).as_posix()
    return DOWNLOADS_PREFIX + ("" if relative == "." else relative)


_DOWNLOAD_TYPES: tuple[tuple[type[MediaItemBase], type[MediaDownloadBase], str], ...] = (
    (Episode, EpisodeMediaDownload, MediaType.EPISODE.value),
    (MovieExtra, MovieExtraMediaDownload, MediaType.MOVIE_EXTRA.value),
    (Movie, MovieMediaDownload, MediaType.MOVIE.value),
    (Video, VideoMediaDownload, MediaType.VIDEO.value),
)


def _download_type(media: MediaItemBase) -> tuple[type[MediaDownloadBase], str]:
    for media_type, download_type, value in _DOWNLOAD_TYPES:
        if isinstance(media, media_type):
            return download_type, value
    raise AdoptionError(f"VODLoft can't adopt files for {type(media).__name__}")


def sidecar_assets(media_path: Path) -> list[tuple[str, str, Path]]:
    """``(asset_key, kind, path)`` for the sidecars next to a media file that VODLoft recognises."""
    stem = media_path.name[: -len(media_path.suffix)] if media_path.suffix else media_path.name
    found: list[tuple[str, str, Path]] = []
    try:
        names = sorted(entry.name for entry in media_path.parent.iterdir() if entry.is_file())
    except OSError:
        return found
    thumbnail = next(
        (name for extension in _THUMBNAIL_EXTENSIONS for name in (f"{stem}{extension}", f"{stem}-thumb{extension}")
         if name in names),
        None,
    )
    if thumbnail:
        found.append(("artwork", "thumbnail", media_path.parent / thumbnail))
    if f"{stem}.nfo" in names:
        found.append(("nfo", "nfo", media_path.parent / f"{stem}.nfo"))
    for name in names:
        if not name.startswith(f"{stem}."):
            continue
        match = _SUBTITLE.match(name[len(stem):])
        if match is None:
            continue
        language = match.group("language") or "und"
        key = f"subtitles-{language}{'-forced' if match.group('forced') else ''}"
        if all(existing[0] != key for existing in found):
            found.append((key, "subtitle", media_path.parent / name))
    return found


def find_file(path: Path) -> FoundFile:
    """Read a file inside the download folder and its sidecars, for :func:`adopt`. Reading a file on a
    network mount can take a while, so this runs before the transaction that adopts it."""
    root = download_root()
    path = path.resolve()
    if not path.is_relative_to(root):
        raise AdoptionError(f"{path} is outside the download folder")
    if not path.is_file():
        raise AdoptionError(f"{path} is not a file")
    identity = inspect_artifact(path)
    assets = []
    for asset_key, kind, asset_path in sidecar_assets(path):
        try:
            assets.append(FoundAsset(asset_key, kind, asset_path, inspect_artifact(asset_path)))
        except (OSError, ValueError):
            continue
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return FoundFile(path, identity, modified_at, tuple(assets))


def adopt(
    session: Session,
    *,
    media: MediaItemBase,
    local_media_profile: LocalMediaProfileBase,
    found: FoundFile,
    matched_by: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Adopted:
    """Record the found file as the available download of ``media`` for ``local_media_profile``."""
    path = found.path
    download_type, type_value = _download_type(media)
    existing = session.scalar(
        select(MediaDownloadBase).where(
            MediaDownloadBase.media_item_id == media.id,
            MediaDownloadBase.local_media_profile_id == local_media_profile.id,
        )
    )
    if existing is not None and existing.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value:
        if Path(existing.file_path).resolve() == path:
            return Adopted(existing, False)
        raise AdoptionError(f"{media.id} already has a file for this profile: {existing.file_path}")
    taken = session.scalar(
        select(MediaDownloadBase.id).where(
            MediaDownloadBase.file_path == str(path),
            MediaDownloadBase.artifact_status != MediaDownloadArtifactStatus.ABSENT.value,
        )
    )
    if taken is not None and (existing is None or taken != existing.id):
        raise AdoptionError(f"{path} already belongs to another download")

    identity = found.identity
    created = existing is None
    download = existing or download_type(
        type=type_value, media_item_id=media.id, local_media_profile_id=local_media_profile.id, file_path="",
    )
    if created:
        session.add(download)
    download.file_path = str(path)
    download.artifact_stat_dev, download.artifact_stat_ino = identity.stat_dev, identity.stat_ino
    download.artifact_size_bytes, download.artifact_fingerprint = identity.size_bytes, identity.fingerprint
    download.artifact_status = MediaDownloadArtifactStatus.AVAILABLE.value
    download.artifact_error = None
    download.downloaded_bytes = identity.size_bytes
    download.downloaded_at = found.modified_at
    if isinstance(download, EpisodeMediaDownload) and isinstance(media, Episode):
        download.downloaded_publish_status = media.publish_status
        if download.download_profile_id is None:
            # The Collection's Download Profile for this Local Media Profile manages the file from now on,
            # so its retention deletes it like a file it downloaded itself.
            download.download_profile_id = session.scalar(select(DownloadProfile.id).where(
                DownloadProfile.collection_id == media.collection_id,
                DownloadProfile.local_media_profile_id == local_media_profile.id,
            ))
        profile = session.get(DownloadProfile, download.download_profile_id) if download.download_profile_id else None
        schedule_imported_upgrade_check(
            download, profile, media.published_date, collection_site(media.collection), datetime.now(timezone.utc),
        )
    download.assets.clear()
    session.flush()
    for asset in found.assets:
        download.assets.append(MediaDownloadAsset(
            asset_key=asset.asset_key, kind=asset.kind, path=str(asset.path), suffix=asset.path.name[len(path.stem):],
            size_bytes=asset.identity.size_bytes, fingerprint=asset.identity.fingerprint,
        ))
    session.flush()
    record_media_download_history(session, download.id, MediaDownloadHistoryAction.IMPORTED, metadata={
        "file_path": str(path),
        "local_media_profile_id": local_media_profile.id,
        **({"matched_by": matched_by} if matched_by else {}),
        **dict(metadata or {}),
    })
    return Adopted(download, created)
