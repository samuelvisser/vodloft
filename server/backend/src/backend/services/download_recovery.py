from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.db import get_session
from downloader.storage.identity import ArtifactIdentity
from downloader import storage
from downloader.storage import temporary

# The scheduled-work pause that startup holds while it recovers the download filesystem.
STARTUP_RECOVERY_PAUSE_OWNER = "startup-download-filesystem-recovery"


def _is_committed_download_artifact(path: Path, identity: ArtifactIdentity) -> bool:
    """Return whether the database owns this exact published media content."""
    from sqlalchemy import select

    from backend.db.models.media_download import MediaDownloadBase
    from backend.types.download_profile_types import MediaDownloadArtifactStatus

    session = get_session()
    try:
        statement = (
            select(
                MediaDownloadBase.artifact_stat_dev,
                MediaDownloadBase.artifact_stat_ino,
                MediaDownloadBase.artifact_size_bytes,
                MediaDownloadBase.artifact_fingerprint,
            )
            .where(
                MediaDownloadBase.file_path == str(path),
                MediaDownloadBase.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value,
            )
        )
        for row in session.execute(statement):
            # Content identity is the portable path for NAS/network filesystems,
            # whose inode/device identifiers may change between mounts. Keep the
            # filesystem identity fast path for older rows without a fingerprint.
            if (
                row.artifact_size_bytes == identity.size_bytes
                and row.artifact_fingerprint
                and row.artifact_fingerprint == identity.fingerprint
            ):
                return True
            if (
                row.artifact_stat_dev == identity.stat_dev
                and row.artifact_stat_ino == identity.stat_ino
            ):
                return True
        return False
    finally:
        session.close()


def cleanup_abandoned_temporary_downloads(temporary_root: str | Path, download_root: str | Path) -> int:
    """Supply database ownership to the standalone filesystem reconciler."""
    return temporary.cleanup_abandoned_temporary_downloads(
        temporary_root, download_root, is_committed=_is_committed_download_artifact,
    )


@dataclass(frozen=True)
class DownloadFilesystemRecovery:
    reservations: int
    temporary_workspaces: int
    rss_cache_files: int
    quick_downloads: int = 0


def recover_download_filesystem(download_settings) -> DownloadFilesystemRecovery:
    """Clean up what an unclean shutdown left in the download folders. Run it while no download runs."""
    from backend.api.endpoints.feeds.cached_video import cleanup_expired_rss_cache
    from backend.services.quick_downloads import sweep_quick_downloads

    # Unfinished quick downloads cannot resume, so their folders go; ready
    # files stay until they expire.
    quick = sweep_quick_downloads(download_settings.temporary_download_root, remove_unfinished=True)
    return DownloadFilesystemRecovery(
        reservations=storage.cleanup_abandoned_download_path_reservations(download_settings.download_root),
        temporary_workspaces=cleanup_abandoned_temporary_downloads(
            download_settings.temporary_download_root,
            download_settings.download_root,
        ),
        rss_cache_files=cleanup_expired_rss_cache(),
        quick_downloads=len(quick.unfinished) + len(quick.expired),
    )
