from datetime import date, datetime

from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Date, ForeignKey, JSON, Table, func
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.db import Base
from backend.db.datetime_types import UTCDateTime
from backend.db.mixins.HasTaskResourcesMixin import HasTaskResourcesMixin

if TYPE_CHECKING:
    from backend.db.models import EpisodeMediaDownload, LocalMediaProfileBase, Season, Show


download_profile_seasons = Table(
    "download_profile_seasons",
    Base.metadata,
    Column("download_profile_id", ForeignKey("download_profiles.id", ondelete="CASCADE"), primary_key=True),
    Column("season_id", ForeignKey("seasons.id", ondelete="CASCADE"), primary_key=True),
)


class DownloadProfile(Base, HasTaskResourcesMixin):
    """Which episodes of a show to download automatically.

    The options that apply follow the show's episode identification: every show
    uses the episode-type and date filters, and a seasonal show also filters by
    season.
    """

    __tablename__ = "download_profiles"
    __task_resource_types__ = ("download_profile",)

    # Columns
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"))
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

    # Season filter, used only when the show is identified by season
    include_upcoming_seasons: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    show: Mapped["Show"] = relationship(back_populates="download_profiles")
    local_media_profile: Mapped["LocalMediaProfileBase"] = relationship(back_populates="download_profiles")
    seasons: Mapped[list["Season"]] = relationship(secondary=download_profile_seasons)

    episode_downloads: Mapped[list["EpisodeMediaDownload"]] = relationship(
        back_populates="download_profile"
    )


    def __repr__(self) -> str:
        return f"<DownloadProfile(id={self.id}, show_id={self.show_id}, enable_profile={self.enable_profile}, created_at={self.created_at}, updated_at={self.updated_at})>"
