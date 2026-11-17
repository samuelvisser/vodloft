from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .StreamProfileBase import StreamProfileBase
from backend.types.local_media_profile_types import PreferredFormat
from backend.types.stream_profile_types import RSS_OUTPUT_MODE_MEDIA_KINDS, StreamMediaKind, StreamProfileType


class RssStreamProfile(StreamProfileBase):
    __tablename__ = "stream_profiles_rss"
    __mapper_args__ = {"polymorphic_identity": StreamProfileType.RSS.value}

    id: Mapped[int] = mapped_column(
        ForeignKey("stream_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    feed_url: Mapped[str]
    video_output_mode: Mapped[str | None] = mapped_column(nullable=True)

    @property
    def media_kinds(self) -> tuple[StreamMediaKind, ...]:
        if self.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value:
            return ("audio",)
        return RSS_OUTPUT_MODE_MEDIA_KINDS.get(self.video_output_mode, ("mp4",))

    def __repr__(self) -> str:
        return (
            f"<RssStreamProfile(id={self.id}, feed_url={self.feed_url}, "
            f"video_output_mode={self.video_output_mode}, max_items={self.max_items}, "
            f"stream_live_episodes={self.stream_live_episodes}, "
            f"enable_profile={self.enable_profile}, created_at={self.created_at}, "
            f"updated_at={self.updated_at})>"
        )
