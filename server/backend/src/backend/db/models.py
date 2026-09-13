from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


collection_videos = Table(
    "collection_videos",
    Base.metadata,
    Column("collection_id", Integer, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
    Column("video_id", Integer, ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True),
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


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
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)

    videos: Mapped[list["Video"]] = relationship(
        secondary=collection_videos,
        back_populates="collections",
        lazy="selectin",
    )


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
    downloaded_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    downloaded_format: Mapped[str | None] = mapped_column(String(128), nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(nullable=True)

    collections: Mapped[list[Collection]] = relationship(
        secondary=collection_videos,
        back_populates="videos",
        lazy="selectin",
    )


class LocalMediaProfile(Base, TimestampMixin):
    __tablename__ = "local_media_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    media_kind: Mapped[str] = mapped_column(String(16))
    output_template: Mapped[str] = mapped_column(Text)

    download_profiles: Mapped[list["DownloadProfile"]] = relationship(back_populates="local_media_profile")


class DownloadProfile(Base, TimestampMixin):
    __tablename__ = "download_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    local_media_profile_id: Mapped[int] = mapped_column(ForeignKey("local_media_profiles.id"))
    format_selector: Mapped[str] = mapped_column(Text, default="bestvideo*+bestaudio/best")
    merge_output_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audio_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    write_subtitles: Mapped[bool] = mapped_column(Boolean, default=False)
    embed_metadata: Mapped[bool] = mapped_column(Boolean, default=True)
    embed_thumbnail: Mapped[bool] = mapped_column(Boolean, default=False)

    local_media_profile: Mapped[LocalMediaProfile] = relationship(back_populates="download_profiles", lazy="joined")


class StreamProfile(Base, TimestampMixin):
    __tablename__ = "stream_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    format_selector: Mapped[str] = mapped_column(
        Text,
        default="best[protocol^=http][vcodec!=none][acodec!=none]/best",
    )
