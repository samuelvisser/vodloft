from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, computed_field, field_validator, model_validator

from backend.api.models.stream_profile_fields import StreamProfileFieldsIn, StreamProfileFieldsOut
from backend.types.stream_profile_types import StreamProfileType


# ---------- Strict input (create/update) ----------
class _IptvStreamProfileAPIBaseIn(StreamProfileFieldsIn):
    channel_number: Optional[int] = Field(
        default=None, ge=1, le=99999, description="Empty takes the number after the owner's highest channel",
    )
    channel_group: Optional[str] = Field(default=None, description="Empty uses the collection's Site name")

    @field_validator("channel_group")
    @classmethod
    def _blank_group_is_none(cls, value: Optional[str]) -> Optional[str]:
        value = (value or "").strip()
        return value or None

    @model_validator(mode="after")
    def _live_needs_video(self):
        if self.stream_live_episodes and self.audio_only:
            raise ValueError("Live episode streaming requires a video preferred format")
        return self


class IptvStreamProfileAPICreate(_IptvStreamProfileAPIBaseIn):
    """Request body for creating an IPTV stream profile."""

    collection_id: int


class IptvStreamProfileAPIUpdate(_IptvStreamProfileAPIBaseIn):
    """Request body for updating an IPTV stream profile."""


# ---------- Lenient output (read) ----------
class IptvStreamProfileAPIRead(StreamProfileFieldsOut):
    """Response body for an IPTV stream profile, with the addresses of its own playlist and guide."""

    type: Literal["iptv"] = StreamProfileType.IPTV.value
    channel_number: int
    channel_group: Optional[str]
    token: str = Field(exclude=True)

    @computed_field
    @property
    def playlist_path(self) -> str:
        return f"/iptv/{self.token}/playlist.m3u"

    @computed_field
    @property
    def guide_path(self) -> str:
        return f"/iptv/{self.token}/guide.xml"
