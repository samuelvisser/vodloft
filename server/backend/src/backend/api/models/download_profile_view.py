from __future__ import annotations

from typing import Optional

from pydantic import AliasPath, Field

from backend.api.models.download_profile import DownloadProfileAPIRead
from backend.api.models.pagination import CursorPageRead


class DownloadProfileAPIReadView(DownloadProfileAPIRead):
    """Denormalized download-profile view sourced from ORM relationships."""

    collection_title: str = Field(validation_alias=AliasPath("profile", "collection", "title"))
    collection_slug: str = Field(validation_alias=AliasPath("profile", "collection", "slug"))
    collection_type: str = Field(validation_alias=AliasPath("profile", "collection", "type"))
    collection_source_key: str = Field(validation_alias=AliasPath("profile", "collection", "source_key"))
    collection_site_key: Optional[str] = Field(validation_alias=AliasPath("profile", "collection", "site_key"))
    collection_episode_identifier: str = Field(
        validation_alias=AliasPath("profile", "collection", "episode_identifier")
    )
    local_media_profile_name: str = Field(
        validation_alias=AliasPath("profile", "local_media_profile", "name")
    )
    local_media_profile_preferred_format: str = Field(
        validation_alias=AliasPath("profile", "local_media_profile", "preferred_format")
    )
    storage_size_bytes: int = Field(validation_alias=AliasPath("storage_size_bytes"))


class DownloadProfileViewPageRead(CursorPageRead[DownloadProfileAPIReadView]):
    """One page of the Download Profiles table, and how many profiles its filters leave."""

    total: int
