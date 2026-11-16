from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, computed_field, field_validator

from backend.api.models.stream_profile_fields import StreamProfileFieldsIn, StreamProfileFieldsOut
from backend.types.stream_profile_types import StreamProfileType, WebdavMetadataFiles, WebdavSeasonFolders


# ---------- Strict input (create/update) ----------
class _WebdavStreamProfileAPIBaseIn(StreamProfileFieldsIn):
    folder_name: Optional[str] = Field(default=None, description="Empty uses the profile's title")
    season_folders: WebdavSeasonFolders = WebdavSeasonFolders.SEASON
    metadata_files: WebdavMetadataFiles = WebdavMetadataFiles.NFO_AND_ARTWORK
    # A share lists whole files, so it never has live episodes.
    stream_live_episodes: Literal[False] = False

    @field_validator("folder_name")
    @classmethod
    def _blank_folder_name_is_none(cls, value: Optional[str]) -> Optional[str]:
        value = (value or "").strip()
        return value or None


class WebdavStreamProfileAPICreate(_WebdavStreamProfileAPIBaseIn):
    """Request body for creating a WebDAV stream profile."""

    collection_id: int


class WebdavStreamProfileAPIUpdate(_WebdavStreamProfileAPIBaseIn):
    """Request body for updating a WebDAV stream profile."""


# ---------- Lenient output (read) ----------
class WebdavStreamProfileAPIRead(StreamProfileFieldsOut):
    """Response body for a WebDAV stream profile, with the address of its own share."""

    type: Literal["webdav"] = StreamProfileType.WEBDAV.value
    folder_name: Optional[str]
    season_folders: WebdavSeasonFolders
    metadata_files: WebdavMetadataFiles
    token: str = Field(exclude=True)

    @computed_field
    @property
    def share_path(self) -> str:
        return f"/webdav/{self.token}/"
