from __future__ import annotations

from pydantic import AliasPath, Field

from backend.api.models.download_profile import DownloadProfileAPIRead


class DownloadProfileAPIReadView(DownloadProfileAPIRead):
    """Denormalized download-profile view sourced from ORM relationships."""

    show_title: str = Field(validation_alias=AliasPath("profile", "show", "title"))
    show_slug: str = Field(validation_alias=AliasPath("profile", "show", "slug"))
    show_type: str = Field(validation_alias=AliasPath("profile", "show", "type"))
    show_episode_identifier: str = Field(
        validation_alias=AliasPath("profile", "show", "episode_identifier")
    )
    local_media_profile_name: str = Field(
        validation_alias=AliasPath("profile", "local_media_profile", "name")
    )
    local_media_profile_preferred_format: str = Field(
        validation_alias=AliasPath("profile", "local_media_profile", "preferred_format")
    )
