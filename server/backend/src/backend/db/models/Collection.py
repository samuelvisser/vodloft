from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from backend.db.models import DownloadProfile, StreamProfile, Video


collection_videos = Table(
    "collection_videos",
    Base.metadata,
    Column("collection_id", Integer, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
    Column("video_id", Integer, ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True),
)


class Collection(Base, TimestampMixin):
    __tablename__ = "collections"
    __table_args__ = (UniqueConstraint("extractor", "extractor_id", name="uq_collection_extractor_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    source_url: Mapped[str] = mapped_column(Text, unique=True)
    extractor: Mapped[str] = mapped_column(String(128), index=True)
    extractor_id: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploader: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploader_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    videos: Mapped[list["Video"]] = relationship(
        "Video",
        secondary=collection_videos,
        back_populates="collections",
        lazy="selectin",
    )
    download_profiles: Mapped[list["DownloadProfile"]] = relationship(
        "DownloadProfile",
        back_populates="collection",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    stream_profiles: Mapped[list["StreamProfile"]] = relationship(
        "StreamProfile",
        back_populates="collection",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
