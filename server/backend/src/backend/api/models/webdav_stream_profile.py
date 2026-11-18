from __future__ import annotations

from typing import Literal

from pydantic import Field, computed_field

from backend.api.models.stream_profile_fields import StreamProfileFieldsIn, StreamProfileFieldsOut
from backend.types.stream_profile_types import StreamProfileType, WebdavMetadataFiles, WebdavSeasonFolders


# ---------- Strict input (create/update) ----------
class _WebdavStreamProfileAPIBaseIn(StreamProfileFieldsIn):
    season_folders: WebdavSeasonFolders = WebdavSeasonFolders.SEASON
    episode_extras: bool = False
    metadata_files: WebdavMetadataFiles = WebdavMetadataFiles.NFO_AND_ARTWORK
    # A share lists whole files, so only downloads, and never live episodes.
    use_downloads: Literal[True] = True
    use_source_stream: Literal[False] = False
    stream_live_episodes: Literal[False] = False


class WebdavStreamProfileAPICreate(_WebdavStreamProfileAPIBaseIn):
    """Request body for creating a WebDAV stream profile."""

    collection_id: int


class WebdavStreamProfileAPIUpdate(_WebdavStreamProfileAPIBaseIn):
    """Request body for updating a WebDAV stream profile."""


# ---------- Lenient output (read) ----------
class WebdavStreamProfileAPIRead(StreamProfileFieldsOut):
    """Response body for a WebDAV stream profile, with the address of its own share."""

    type: Literal["webdav"] = StreamProfileType.WEBDAV.value
    season_folders: WebdavSeasonFolders
    episode_extras: bool
    metadata_files: WebdavMetadataFiles
    token: str = Field(exclude=True)

    @computed_field
    @property
    def share_path(self) -> str:
        return f"/webdav/{self.token}/"
