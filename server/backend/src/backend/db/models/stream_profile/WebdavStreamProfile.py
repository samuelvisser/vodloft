from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .StreamProfileBase import StreamProfileBase
from backend.types.local_media_profile_types import PreferredFormat
from backend.types.stream_profile_types import (
    StreamMediaKind,
    StreamProfileType,
    WebdavMetadataFiles,
    WebdavSeasonFolders,
)


class WebdavStreamProfile(StreamProfileBase):
    """A read-only network folder for media players, laid out as a TV show."""

    __tablename__ = "stream_profiles_webdav"
    __mapper_args__ = {"polymorphic_identity": StreamProfileType.WEBDAV.value}

    # A share lists whole files, never the Site's stream.
    passes_site_streams = False

    id: Mapped[int] = mapped_column(
        ForeignKey("stream_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    folder_name: Mapped[Optional[str]] = mapped_column(
        nullable=True, default=None, comment="The show's folder; empty uses the profile's title",
    )
    season_folders: Mapped[str] = mapped_column(
        String(16), default=WebdavSeasonFolders.SEASON.value,
        comment="How the episodes are sorted into folders: a WebdavSeasonFolders value",
    )
    metadata_files: Mapped[str] = mapped_column(
        String(32), default=WebdavMetadataFiles.NFO_AND_ARTWORK.value,
        comment="What is listed beside the episodes for media players: a WebdavMetadataFiles value",
    )

    @property
    def media_kinds(self) -> tuple[StreamMediaKind, ...]:
        # A media player seeks in a whole file, so the share lists files only, never a stream.
        if self.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value:
            return ("audio",)
        return ("mp4",)

    def __repr__(self) -> str:
        return (
            f"<WebdavStreamProfile(id={self.id}, folder_name={self.folder_name}, "
            f"season_folders={self.season_folders}, enable_profile={self.enable_profile})>"
        )
