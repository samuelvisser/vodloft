from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from backend.db.models import LocalMediaProfile, Video


class MediaDownload(Base, TimestampMixin):
    __tablename__ = "media_downloads"
    __table_args__ = (
        UniqueConstraint(
            "video_id",
            "local_media_profile_id",
            name="uq_media_download_video_profile",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    local_media_profile_id: Mapped[int] = mapped_column(
        ForeignKey("local_media_profiles.id"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    downloaded_bytes: Mapped[int | None] = mapped_column(nullable=True)
    format_downloaded: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    task_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    video: Mapped["Video"] = relationship("Video", back_populates="media_downloads")
    local_media_profile: Mapped["LocalMediaProfile"] = relationship(
        "LocalMediaProfile",
        back_populates="media_downloads",
        lazy="joined",
    )
