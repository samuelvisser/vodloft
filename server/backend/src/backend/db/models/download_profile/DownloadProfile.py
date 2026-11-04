from datetime import date, datetime

from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Date, ForeignKey, JSON, String, Table, func
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.db import Base
from backend.db.datetime_types import UTCDateTime
from backend.db.mixins.HasTaskResourcesMixin import HasTaskResourcesMixin
from backend.types.download_profile_types import DEFAULT_SPONSORBLOCK_SEGMENTS, DEFAULT_UPGRADE_IMPROVEMENTS

if TYPE_CHECKING:
    from backend.db.models import EpisodeMediaDownload, LocalMediaProfileBase, Season, Collection
    from .DownloadProfileRule import DownloadProfileRule


download_profile_seasons = Table(
    "download_profile_seasons",
    Base.metadata,
    Column("download_profile_id", ForeignKey("download_profiles.id", ondelete="CASCADE"), primary_key=True),
    Column("season_id", ForeignKey("seasons.id", ondelete="CASCADE"), primary_key=True),
)


class DownloadProfile(Base, HasTaskResourcesMixin):
    """Which episodes of a collection to download automatically.

    The options that apply follow the collection's episode identification: every collection
    uses the episode-type and date filters, and a seasonal collection also filters by
    season.
    """

    __tablename__ = "download_profiles"
    __task_resource_types__ = ("download_profile",)

    # Columns
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"))
    local_media_profile_id: Mapped[int] = mapped_column(ForeignKey("local_media_profiles.id"))
    enable_profile: Mapped[bool] = mapped_column(default=True)
    ep_id_type_list: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # Date filters
    download_with_countdown: Mapped[bool] = mapped_column(default=False)
    redownload_final: Mapped[bool] = mapped_column(default=False)
    download_days_in_past: Mapped[int] = mapped_column(default=0)
    download_episode_count: Mapped[int] = mapped_column(default=0)
    download_starting_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    delete_older_episodes: Mapped[bool] = mapped_column(default=True)
    retention_from: Mapped[str] = mapped_column(
        String(16), default="published", server_default="published",
        comment="Whether a date window deletes episodes N days after publication or after downloading",
    )
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
        comment="What counts as a better version: resolution, sponsorblock, subtitles or codec",
    )

    # Season filter, used only when the collection is identified by season
    include_upcoming_seasons: Mapped[bool] = mapped_column(default=True)
    all_seasons: Mapped[bool] = mapped_column(
        default=False, server_default="0",
        comment="The seasons line was removed: every season downloads, upcoming ones included",
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
    seasons: Mapped[list["Season"]] = relationship(secondary=download_profile_seasons)

    rules: Mapped[list["DownloadProfileRule"]] = relationship(
        back_populates="download_profile",
        cascade="all, delete-orphan",
        order_by="DownloadProfileRule.position",
    )
    episode_downloads: Mapped[list["EpisodeMediaDownload"]] = relationship(
        back_populates="download_profile"
    )


    def __repr__(self) -> str:
        return f"<DownloadProfile(id={self.id}, collection_id={self.collection_id}, enable_profile={self.enable_profile}, created_at={self.created_at}, updated_at={self.updated_at})>"
