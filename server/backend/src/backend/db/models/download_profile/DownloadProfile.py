from datetime import datetime

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint, func
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.db import Base
from backend.db.datetime_types import UTCDateTime
from backend.db.mixins.HasTaskResourcesMixin import HasTaskResourcesMixin
from backend.types.download_profile_types import DEFAULT_SPONSORBLOCK_SEGMENTS, DEFAULT_UPGRADE_IMPROVEMENTS

if TYPE_CHECKING:
    from backend.db.models import EpisodeMediaDownload, LocalMediaProfileBase, Collection
    from .DownloadProfileFilter import DownloadProfileFilter


class DownloadProfile(Base, HasTaskResourcesMixin):
    """Which episodes of a collection to download automatically, to one Local Media Profile.

    Which episodes is the ordered list of filters; a collection has at most one
    Download Profile per Local Media Profile.
    """

    __tablename__ = "download_profiles"
    __table_args__ = (
        UniqueConstraint("collection_id", "local_media_profile_id", name="uq_download_profiles_collection_local_media_profile"),
    )
    __task_resource_types__ = ("download_profile",)

    # Columns
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"))
    local_media_profile_id: Mapped[int] = mapped_column(ForeignKey("local_media_profiles.id"), index=True)
    enable_profile: Mapped[bool] = mapped_column(default=True)

    download_with_countdown: Mapped[bool] = mapped_column(default=False)
    redownload_final: Mapped[bool] = mapped_column(default=False)
    # Whether a download its date lines leave out is deleted.
    delete_older_episodes: Mapped[bool] = mapped_column(default=True)
    auto_subtitles: Mapped[str] = mapped_column(
        String(16), default="fallback", server_default="fallback",
        comment="YouTube's auto-generated subtitles: never, fallback (when there is no real one) or always",
    )
    sponsorblock_enabled: Mapped[bool] = mapped_column(default=True, server_default="0")
    sponsorblock_segments: Mapped[dict[str, str]] = mapped_column(
        MutableDict.as_mutable(JSON), default=lambda: dict(DEFAULT_SPONSORBLOCK_SEGMENTS), nullable=False,
        comment="SponsorBlock segment type to keep, chapter or cut, for YouTube Collections",
    )

    # The upgrade check: downloading again later, and keeping the new file only when it is better
    upgrade_check: Mapped[bool] = mapped_column(default=True, server_default="0")
    upgrade_after_days: Mapped[int] = mapped_column(
        default=7, server_default="7", comment="Days after downloading that the upgrade check first looks",
    )
    upgrade_repeat: Mapped[str] = mapped_column(
        String(16), default="once", server_default="once", comment="once, twice (again after 30 days) or every (up to 3 times)",
    )
    upgrade_improvements: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=lambda: list(DEFAULT_UPGRADE_IMPROVEMENTS), nullable=False,
        comment="What counts as a better version: resolution, sponsorblock, subtitles, codec or length",
    )
    upgrade_length_minutes: Mapped[int] = mapped_column(
        default=5, server_default="5", comment="How many minutes longer or shorter counts as a different length",
    )

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    collection: Mapped["Collection"] = relationship(back_populates="download_profiles")
    local_media_profile: Mapped["LocalMediaProfileBase"] = relationship(back_populates="download_profiles")
    filters: Mapped[list["DownloadProfileFilter"]] = relationship(
        back_populates="download_profile",
        cascade="all, delete-orphan",
        order_by="DownloadProfileFilter.position",
    )
    episode_downloads: Mapped[list["EpisodeMediaDownload"]] = relationship(
        back_populates="download_profile"
    )


    def __repr__(self) -> str:
        return f"<DownloadProfile(id={self.id}, collection_id={self.collection_id}, enable_profile={self.enable_profile}, created_at={self.created_at}, updated_at={self.updated_at})>"
