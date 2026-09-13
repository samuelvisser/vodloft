from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from backend.db.models import DownloadProfile, MediaDownload


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

    download_profiles: Mapped[list["DownloadProfile"]] = relationship(
        "DownloadProfile",
        back_populates="local_media_profile",
    )
    media_downloads: Mapped[list["MediaDownload"]] = relationship(
        "MediaDownload",
        back_populates="local_media_profile",
    )
