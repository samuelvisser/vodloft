from __future__ import annotations

from pydantic import AliasPath, Field

from backend.api.models.download_profile import DownloadProfileAPIRead


class DownloadProfileAPIReadView(DownloadProfileAPIRead):
    """Denormalized download-profile view sourced from ORM relationships."""

    collection_title: str = Field(validation_alias=AliasPath("profile", "collection", "title"))
    collection_slug: str = Field(validation_alias=AliasPath("profile", "collection", "slug"))
    collection_type: str = Field(validation_alias=AliasPath("profile", "collection", "type"))
    collection_source_key: str = Field(validation_alias=AliasPath("profile", "collection", "source_key"))
    collection_episode_identifier: str = Field(
        validation_alias=AliasPath("profile", "collection", "episode_identifier")
    )
    local_media_profile_name: str = Field(
        validation_alias=AliasPath("profile", "local_media_profile", "name")
    )
    local_media_profile_preferred_format: str = Field(
        validation_alias=AliasPath("profile", "local_media_profile", "preferred_format")
    )
