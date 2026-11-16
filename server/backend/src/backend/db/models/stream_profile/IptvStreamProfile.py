from typing import Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .StreamProfileBase import StreamProfileBase
from backend.types.local_media_profile_types import PreferredFormat
from backend.types.stream_profile_types import StreamMediaKind, StreamProfileType


class IptvStreamProfile(StreamProfileBase):
    """A TV channel for IPTV apps: an M3U playlist entry and an XMLTV programme guide."""

    __tablename__ = "stream_profiles_iptv"
    __mapper_args__ = {"polymorphic_identity": StreamProfileType.IPTV.value}

    # The channel plays one media of an episode at a time, so it needs only one of them.
    plays_every_media_kind = False

    id: Mapped[int] = mapped_column(
        ForeignKey("stream_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    channel_number: Mapped[int] = mapped_column(comment="Where the channel sits in an app's channel list")
    channel_group: Mapped[Optional[str]] = mapped_column(
        nullable=True, default=None,
        comment="The group an app lists the channel under; empty uses the collection's Site name",
    )

    @property
    def media_kinds(self) -> tuple[StreamMediaKind, ...]:
        if self.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value:
            return ("audio",)
        # HLS plays live and is what IPTV apps expect; a downloaded MP4 plays where there is no HLS.
        return ("hls", "mp4")

    def __repr__(self) -> str:
        return (
            f"<IptvStreamProfile(id={self.id}, channel_number={self.channel_number}, "
            f"channel_group={self.channel_group}, enable_profile={self.enable_profile})>"
        )
