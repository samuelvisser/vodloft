from sqlalchemy import ForeignKey, String, false
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
    """A read-only network folder for media players, laid out as a TV show and named by the profile's title."""

    __tablename__ = "stream_profiles_webdav"
    __mapper_args__ = {"polymorphic_identity": StreamProfileType.WEBDAV.value}

    # A share lists whole files, so only downloads: never the Site's stream.
    streams_from_site = False

    id: Mapped[int] = mapped_column(
        ForeignKey("stream_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    season_folders: Mapped[str] = mapped_column(
        String(16), default=WebdavSeasonFolders.SEASON.value,
        comment="How the episodes are sorted into folders: a WebdavSeasonFolders value",
    )
    episode_extras: Mapped[bool] = mapped_column(
        default=False, server_default=false(),
        comment="List the extras of an episode beside it, named after its file; otherwise in the show's Trailers and Other folders",
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
            f"<WebdavStreamProfile(id={self.id}, overwrite_collection_title={self.overwrite_collection_title}, "
            f"season_folders={self.season_folders}, enable_profile={self.enable_profile})>"
        )
