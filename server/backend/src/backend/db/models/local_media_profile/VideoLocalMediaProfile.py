from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.types.local_media_profile_types import LocalMediaProfileType, VideoLocalMediaProfileScope

from .LocalMediaProfileBase import LocalMediaProfileBase


class VideoLocalMediaProfile(LocalMediaProfileBase):
    __tablename__ = "local_media_profiles_video"
    __mapper_args__ = {"polymorphic_identity": LocalMediaProfileType.VIDEO.value}

    id: Mapped[int] = mapped_column(
        ForeignKey("local_media_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    video_scope: Mapped[str] = mapped_column(
        String(16), default=VideoLocalMediaProfileScope.BOTH.value, server_default=VideoLocalMediaProfileScope.BOTH.value,
        nullable=False, comment="What the profile is offered for: videos, movies or both",
    )
