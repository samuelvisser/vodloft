from __future__ import annotations

from datetime import datetime
from typing import Annotated, Union

from pydantic import AliasPath, Field, computed_field

from backend.api.models.base import ResponseBase, response_model_config
from backend.api.models.pagination import CursorPageRead
from backend.api.models.iptv_stream_profile import IptvStreamProfileAPIRead
from backend.api.models.rss_stream_profile import RssStreamProfileAPIRead
from backend.types.stream_profile_types import StreamProfileType


class StreamProfileAPIRead(ResponseBase):
    """Unified response body for a stream profile (any type).

    Represents the base stream profile record with its discriminator `type`.
    Create/Update/Delete of concrete profiles should be done via the
    type-specific endpoints (RSS or IPTV).
    """

    model_config = response_model_config(nested_source="profile")

    id: int
    collection_id: int
    enable_profile: bool
    use_downloads: bool
    use_source_stream: bool
    preferred_format: str
    prefer_exact_match: bool
    ep_id_type_list: list[str]
    type: StreamProfileType

    created_at: datetime
    updated_at: datetime


class StreamProfileAPIReadView(StreamProfileAPIRead):
    """Denormalized stream-profile view sourced from ORM relationships."""

    collection_title: str = Field(validation_alias=AliasPath("profile", "collection", "title"))
    collection_slug: str = Field(validation_alias=AliasPath("profile", "collection", "slug"))
    collection_source_key: str = Field(validation_alias=AliasPath("profile", "collection", "source_key"))
    stream_profile_impl: Annotated[
        Union[RssStreamProfileAPIRead, IptvStreamProfileAPIRead], Field(discriminator="type"),
    ] = Field(validation_alias="profile")


class StreamProfileViewPageRead(CursorPageRead[StreamProfileAPIReadView]):
    """One page of the Stream Profiles table, and how many profiles its filters leave."""

    total: int


class StreamAccessRead(ResponseBase):
    """The addresses of one playlist and guide with all of the user's channels, for apps that list them all."""

    stream_token: str = Field(exclude=True)

    @computed_field
    @property
    def playlist_path(self) -> str:
        return f"/iptv/{self.stream_token}/playlist.m3u"

    @computed_field
    @property
    def guide_path(self) -> str:
        return f"/iptv/{self.stream_token}/guide.xml"

    @computed_field
    @property
    def episodes_path(self) -> str:
        return f"/iptv/{self.stream_token}/vod.m3u"
