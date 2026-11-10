from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Index, String, event, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.datetime_types import UTCDateTime
from backend.types.local_media_profile_types import (
    AudioCodec,
    AudioFormat,
    CodecFallback,
    LocalMediaProfileMetadataMode,
    LocalMediaProfileStorageMode,
    LocalMediaProfileSubtitleMode,
    LocalMediaProfileThumbnailMode,
    LocalMediaProfileType,
    QualityGoal,
    SubtitleLanguageMode,
    VideoContainer,
    goal_video_codecs,
)

if TYPE_CHECKING:
    from backend.db.models.download_profile import DownloadProfile
    from backend.db.models.media_download import MediaDownloadBase


class LocalMediaProfileBase(Base):
    __tablename__ = "local_media_profiles"
    __table_args__ = (
        Index(
            "uq_local_media_profiles_type_output_template_preferred_format",
            "type",
            "output_template",
            "preferred_format",
            unique=True,
        ),
    )
    __mapper_args__ = {
        "polymorphic_on": "type",
        "polymorphic_identity": LocalMediaProfileType.BASE.value,
    }

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(
        default=LocalMediaProfileType.COLLECTION.value,
        server_default=LocalMediaProfileType.COLLECTION.value,
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(index=True, unique=True)
    name: Mapped[str] = mapped_column(unique=True)
    output_template: Mapped[str]
    preferred_format: Mapped[str]
    download_mode: Mapped[str] = mapped_column(
        String(16),
        default=LocalMediaProfileStorageMode.SYSTEM.value,
        server_default=LocalMediaProfileStorageMode.SYSTEM.value,
        nullable=False,
    )
    thumbnail_mode: Mapped[str] = mapped_column(
        String(24),
        default=LocalMediaProfileThumbnailMode.SYSTEM.value,
        server_default=LocalMediaProfileThumbnailMode.SYSTEM.value,
        nullable=False,
    )
    metadata_mode: Mapped[str] = mapped_column(
        String(24),
        default=LocalMediaProfileMetadataMode.SYSTEM.value,
        server_default=LocalMediaProfileMetadataMode.SYSTEM.value,
        nullable=False,
    )

    subtitle_mode: Mapped[str] = mapped_column(
        String(24),
        default=LocalMediaProfileSubtitleMode.SIDECAR.value,
        server_default=LocalMediaProfileSubtitleMode.SIDECAR.value,
        nullable=False,
    )

    # Subtitle languages in order of preference, and which of them to download.
    subtitle_languages: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["en"], server_default='["en"]', nullable=False)
    subtitle_language_mode: Mapped[str] = mapped_column(
        String(16), default=SubtitleLanguageMode.LISTED.value, server_default=SubtitleLanguageMode.LISTED.value, nullable=False,
    )

    # Quality on sites yt-dlp downloads from. A goal other than custom fixes
    # the codec order, container and audio codec to that goal's.
    quality_goal: Mapped[str] = mapped_column(
        String(16), default=QualityGoal.COMPATIBILITY.value, server_default=QualityGoal.COMPATIBILITY.value, nullable=False,
    )
    # [{"codec": "h264", "allowed": true}, ...], most wanted first.
    video_codecs: Mapped[list[dict]] = mapped_column(
        JSON, default=lambda: goal_video_codecs(QualityGoal.COMPATIBILITY), nullable=False,
    )
    codec_fallback: Mapped[str] = mapped_column(
        String(8), default=CodecFallback.BEST.value, server_default=CodecFallback.BEST.value, nullable=False,
    )
    container: Mapped[str] = mapped_column(
        String(8), default=VideoContainer.MP4.value, server_default=VideoContainer.MP4.value, nullable=False,
    )
    audio_codec: Mapped[str] = mapped_column(
        String(8), default=AudioCodec.AAC.value, server_default=AudioCodec.AAC.value, nullable=False,
    )
    audio_format: Mapped[str] = mapped_column(
        String(8), default=AudioFormat.M4A.value, server_default=AudioFormat.M4A.value, nullable=False,
    )
    # A dubbed audio track's language code; None keeps the original language.
    audio_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    site_keys: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, server_default="[]",
        comment="The Sites this profile is offered for",
    )
    """A new profile without a list starts with every Site VODLoft knows that can use its type."""
    include_upcoming_sites: Mapped[bool] = mapped_column(
        default=True, server_default=true(), nullable=False,
        comment="Sites VODLoft sees for the first time join the profile's Sites",
    )

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    download_profiles: Mapped[list["DownloadProfile"]] = relationship(
        back_populates="local_media_profile",
        passive_deletes="all",
    )
    media_downloads: Mapped[list["MediaDownloadBase"]] = relationship(
        back_populates="local_media_profile",
        passive_deletes="all",
    )

    def __repr__(self) -> str:
        return (
            f"<LocalMediaProfileBase(id={self.id}, type={self.type}, slug={self.slug}, "
            f"name={self.name}, created_at={self.created_at}, updated_at={self.updated_at})>"
        )


@event.listens_for(LocalMediaProfileBase, "before_insert", propagate=True)
def _offer_every_known_site(_mapper, connection, target: LocalMediaProfileBase) -> None:
    if target.site_keys is None:
        from backend.services.local_media_profile_sites import every_known_site

        target.site_keys = every_known_site(connection, target.type)
