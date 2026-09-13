from __future__ import annotations

import secrets
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Table, Text, UniqueConstraint
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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

    videos: Mapped[list["Video"]] = relationship(secondary=collection_videos, back_populates="collections", lazy="selectin")
    download_profiles: Mapped[list["DownloadProfile"]] = relationship(back_populates="collection", cascade="all, delete-orphan", lazy="selectin")
    stream_profiles: Mapped[list["StreamProfile"]] = relationship(back_populates="collection", cascade="all, delete-orphan", lazy="selectin")


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

    collections: Mapped[list[Collection]] = relationship(secondary=collection_videos, back_populates="videos", lazy="selectin")
    media_downloads: Mapped[list["MediaDownload"]] = relationship(back_populates="video", cascade="all, delete-orphan", lazy="selectin")


class LocalMediaProfile(Base, TimestampMixin):
    __tablename__ = "local_media_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slug: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    scope: Mapped[str] = mapped_column(String(16), default="video", index=True)
    media_kind: Mapped[str] = mapped_column(String(16))
    output_template: Mapped[str] = mapped_column(Text)
    preferred_format: Mapped[str] = mapped_column(Text, default="bestvideo*+bestaudio/best")
    merge_output_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audio_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    write_subtitles: Mapped[bool] = mapped_column(Boolean, default=False)
    embed_metadata: Mapped[bool] = mapped_column(Boolean, default=True)
    embed_thumbnail: Mapped[bool] = mapped_column(Boolean, default=False)

    download_profiles: Mapped[list["DownloadProfile"]] = relationship(back_populates="local_media_profile")
    media_downloads: Mapped[list["MediaDownload"]] = relationship(back_populates="local_media_profile")


class DownloadProfile(Base, TimestampMixin):
    __tablename__ = "download_profiles"
    __table_args__ = (UniqueConstraint("collection_id", "local_media_profile_id", name="uq_download_profile_collection_media"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), nullable=True, index=True)
    local_media_profile_id: Mapped[int] = mapped_column(ForeignKey("local_media_profiles.id"))
    enable_profile: Mapped[bool] = mapped_column(Boolean, default=True)

    collection: Mapped[Collection | None] = relationship(back_populates="download_profiles")
    local_media_profile: Mapped[LocalMediaProfile] = relationship(back_populates="download_profiles", lazy="joined")


class StreamProfile(Base, TimestampMixin):
    __tablename__ = "stream_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), nullable=True, index=True)
    enable_profile: Mapped[bool] = mapped_column(Boolean, default=True)
    use_downloads: Mapped[bool] = mapped_column(Boolean, default=False)
    format_selector: Mapped[str] = mapped_column(Text, default="best[protocol^=http][vcodec!=none][acodec!=none]/best")

    collection: Mapped[Collection | None] = relationship(back_populates="stream_profiles")


class MediaDownload(Base, TimestampMixin):
    __tablename__ = "media_downloads"
    __table_args__ = (UniqueConstraint("video_id", "local_media_profile_id", name="uq_media_download_video_profile"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    local_media_profile_id: Mapped[int] = mapped_column(ForeignKey("local_media_profiles.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    downloaded_bytes: Mapped[int | None] = mapped_column(nullable=True)
    format_downloaded: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    task_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    video: Mapped[Video] = relationship(back_populates="media_downloads")
    local_media_profile: Mapped[LocalMediaProfile] = relationship(back_populates="media_downloads", lazy="joined")


class TaskDefinition(Base, TimestampMixin):
    __tablename__ = "task_definitions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    allowed_resource_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_max_retries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tracks_progress: Mapped[bool] = mapped_column(Boolean, default=True)


class TaskOperation(Base, TimestampMixin):
    __tablename__ = "task_operations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32), default="api", index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    total_tasks: Mapped[int] = mapped_column(Integer, default=0)
    completed_tasks: Mapped[int] = mapped_column(Integer, default=0)
    succeeded_tasks: Mapped[int] = mapped_column(Integer, default=0)
    failed_tasks: Mapped[int] = mapped_column(Integer, default=0)
    canceled_tasks: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskSchedule(Base, TimestampMixin):
    __tablename__ = "task_schedules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("task_definitions.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32), default="user", index=True)
    registry_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    resource_type: Mapped[str] = mapped_column(String(32), default="system", index=True)
    resource_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), default="cron")
    trigger_args: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    coalesce: Mapped[bool] = mapped_column(Boolean, default=True)
    max_retries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_run_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    definition: Mapped[TaskDefinition] = relationship(lazy="joined")


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("task_definitions.id", ondelete="CASCADE"), index=True)
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("task_schedules.id", ondelete="SET NULL"), nullable=True, index=True)
    operation_id: Mapped[int | None] = mapped_column(ForeignKey("task_operations.id", ondelete="SET NULL"), nullable=True, index=True)
    resource_type: Mapped[str] = mapped_column(String(32), index=True)
    resource_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    source: Mapped[str] = mapped_column(String(32), default="api", index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    priority_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runtime_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    definition: Mapped[TaskDefinition] = relationship(lazy="joined")
    schedule: Mapped[TaskSchedule | None] = relationship(lazy="joined")
    operation: Mapped[TaskOperation | None] = relationship(lazy="joined")


class ApplicationSettings(Base, TimestampMixin):
    __tablename__ = "application_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    alembic_version_num: Mapped[str | None] = mapped_column(String(64), nullable=True)
    auth_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_username: Mapped[str] = mapped_column(String(128), default="admin")
    admin_password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_secret: Mapped[str] = mapped_column(String(255), default=lambda: secrets.token_urlsafe(48))
    rss_token: Mapped[str] = mapped_column(String(255), default=lambda: secrets.token_urlsafe(32), unique=True)
    rss_item_limit: Mapped[int] = mapped_column(Integer, default=200)
