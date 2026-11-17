"""The fields every stream profile type has, for its own request and response models."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import AliasPath, Field, computed_field, field_validator

from backend.api.models.base import RequestBase, ResponseBase
from backend.types.download_profile_types import EpIdType, EpisodeTagKey
from backend.types.local_media_profile_types import PreferredFormat


def _default_episode_types() -> list[str]:
    return [EpIdType.EP.value, EpIdType.AUX.value]


class StreamProfileFieldsIn(RequestBase):
    """Fields for requests: validate here (constraints allowed)."""

    title: str = Field(min_length=1)
    enable_profile: bool
    use_downloads: bool
    use_source_stream: bool
    preferred_format: str = Field(min_length=1)
    prefer_exact_match: bool
    ep_id_type_list: list[EpisodeTagKey] = Field(default_factory=_default_episode_types)
    stream_live_episodes: bool = False
    proxy_source_stream: bool = True
    max_items: int = Field(default=0, ge=0)

    @field_validator("title")
    @classmethod
    def _title_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be blank")
        return value

    @field_validator("preferred_format")
    @classmethod
    def _stream_preferred_format_must_be_playback_media(cls, value: str) -> str:
        if value == PreferredFormat.FORMAT_HLS:
            raise ValueError(
                "HLS is a Local Media Profile download format, not a Stream Profile preferred format"
            )
        return value

    @property
    def audio_only(self) -> bool:
        return self.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value


class StreamProfileFieldsOut(ResponseBase):
    """Fields for responses: no validators, no constraints."""

    id: int
    collection_id: int
    overwrite_collection_title: Optional[str] = Field(exclude=True)
    collection_title: str = Field(validation_alias=AliasPath("collection", "title"), exclude=True)
    enable_profile: bool
    use_downloads: bool
    use_source_stream: bool
    preferred_format: str
    prefer_exact_match: bool
    ep_id_type_list: list[str]
    stream_live_episodes: bool
    proxy_source_stream: bool
    max_items: int
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def effective_title(self) -> str:
        return self.overwrite_collection_title or self.collection_title
