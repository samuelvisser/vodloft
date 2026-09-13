from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from backend.db.models import Collection, MediaDownload


class Video(Base, TimestampMixin):
    __tablename__ = "videos"
    __table_args__ = (UniqueConstraint("extractor", "extractor_id", name="uq_video_extractor_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_url: Mapped[str] = mapped_column(Text, unique=True)
    extractor: Mapped[str] = mapped_column(String(128), index=True)
    extractor_id: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploader: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploader_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    upload_date: Mapped[date | None] = mapped_column(nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    standalone: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    collections: Mapped[list["Collection"]] = relationship(
        "Collection",
        secondary="collection_videos",
        back_populates="videos",
        lazy="selectin",
    )
    media_downloads: Mapped[list["MediaDownload"]] = relationship(
        "MediaDownload",
        back_populates="video",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
