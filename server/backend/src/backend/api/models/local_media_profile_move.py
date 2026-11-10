from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import AliasPath, Field

from backend.types.local_media_profile_types import EpisodeMoveOutcome

from .base import RequestBase, ResponseBase


class LocalMediaProfileMoveCollectionAPIRequest(RequestBase):
    collection_id: int = Field(gt=0)
    move_download_profile: bool = False


class LocalMediaProfileMoveAPIRequest(RequestBase):
    target_slug: str = Field(min_length=1)
    collections: list[LocalMediaProfileMoveCollectionAPIRequest] = Field(min_length=1)


class LocalMediaProfileMoveTargetAPIRead(ResponseBase):
    id: int
    slug: str
    name: str


class LocalMediaProfileMoveDownloadProfileAPIRead(ResponseBase):
    id: int
    enable_profile: bool
    delete_older_episodes: bool


class LocalMediaProfileMoveEpisodeAPIRead(ResponseBase):
    media_download_id: int = Field(validation_alias=AliasPath("download", "id"))
    episode_id: int = Field(validation_alias=AliasPath("download", "media_item_id"))
    episode_slug: str = Field(validation_alias=AliasPath("download", "media", "slug"))
    episode_title: str = Field(validation_alias=AliasPath("download", "media", "title"))
    outcome: EpisodeMoveOutcome
    source_path: Path = Field(validation_alias="source")
    destination_path: Optional[Path] = Field(default=None, validation_alias="destination")


class LocalMediaProfileMoveCollectionAPIRead(ResponseBase):
    collection_id: int = Field(validation_alias=AliasPath("collection", "id"))
    collection_slug: str = Field(validation_alias=AliasPath("collection", "slug"))
    collection_title: str = Field(validation_alias=AliasPath("collection", "title"))
    in_scope: bool
    type_offered: bool
    """Whether the target is for this type of Collection."""
    site_offered: bool
    """Whether the target is offered for the Collection's Site."""
    blocked: bool
    can_move_download_profile: bool
    retention_at_risk: int
    source_download_profiles: list[LocalMediaProfileMoveDownloadProfileAPIRead]
    target_download_profiles: list[LocalMediaProfileMoveDownloadProfileAPIRead]
    episodes: list[LocalMediaProfileMoveEpisodeAPIRead]


class LocalMediaProfileMovePreviewAPIRead(ResponseBase):
    target: LocalMediaProfileMoveTargetAPIRead
    collections: list[LocalMediaProfileMoveCollectionAPIRead]
