"""How much disk space downloads take, as the profile tables show it."""
from __future__ import annotations

from sqlalchemy import case, func
from sqlalchemy.sql.elements import ColumnElement

from backend.db.models import MediaDownloadBase
from backend.types.download_profile_types import MediaDownloadArtifactStatus

_PHYSICAL_DOWNLOAD_STATUSES = (
    MediaDownloadArtifactStatus.AVAILABLE.value,
    MediaDownloadArtifactStatus.CORRUPTED.value,
)


def is_physical_download() -> ColumnElement[bool]:
    """A download whose file is on disk, even when that file is damaged."""
    return MediaDownloadBase.artifact_status.in_(_PHYSICAL_DOWNLOAD_STATUSES)


def storage_size_bytes_sum() -> ColumnElement[int]:
    """The summed file size of the physical downloads in a grouped query."""
    return func.coalesce(
        func.sum(
            case(
                (is_physical_download(), func.coalesce(MediaDownloadBase.artifact_size_bytes, 0)),
                else_=0,
            )
        ),
        0,
    )
