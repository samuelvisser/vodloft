from datetime import datetime
from typing import Optional, TYPE_CHECKING, TypeAlias

from sqlalchemy import ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.db import Base
from backend.db.datetime_types import UTCDateTime
from backend.db.mixins.HasMetadataMixin import HasMetadataMixin
from backend.db.mixins.MediaContentMetadataMixin import PICTURE_PATH_COMMENT
from backend.db.mixins.HasTaskResourcesMixin import HasTaskResourcesMixin
from backend.db.mixins.CreatedByMixin import CreatedByMixin
from backend.types.collection_types import EpisodeOrder

if TYPE_CHECKING:
    from backend.db.models.media_item import Episode
    from backend.db.models.stream_profile import StreamProfileBase
    from backend.db.models import Season, DownloadProfile, Site
    from backend.db.models import CustomIndexState


def _default_episode_order(context) -> str:
    return EpisodeOrder.default_for(context.get_current_parameters()["episode_identifier"]).value


class Collection(Base, HasMetadataMixin, HasTaskResourcesMixin, CreatedByMixin):
    __tablename__ = "collections"
    __task_resource_types__ = ("collection",)
    # The same collection is added once per Site, whichever Source fetches it.
    __table_args__ = (UniqueConstraint("site_key", "site_ref"),)

    # Columns
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(index=True, unique=True)
    source_key: Mapped[str] = mapped_column(index=True, comment="Id of the Source this comes from, as registered in sources")
    slug: Mapped[str] = mapped_column(index=True, unique=True)
    site_key: Mapped[Optional[str]] = mapped_column(
        ForeignKey("sites.key"), index=True, comment="The Site the collection is on; filled in the background for older collections",
    )
    site_ref: Mapped[Optional[str]] = mapped_column(comment="The Site's own id for the collection")
    title: Mapped[str]
    description: Mapped[Optional[str]]
    sharing_url: Mapped[str] = mapped_column(unique=True)
    ytdlp_options: Mapped[str] = mapped_column(
        Text, default="", server_default="",
        comment="Your own yt-dlp options for this Collection, added after the yt-dlp Source's",
    )
    cookies_mode: Mapped[str] = mapped_column(
        default="automatic", server_default="automatic",
        comment="When downloads use the Source's cookies file: automatic, never or always",
    )
    cookies_needed_until: Mapped[Optional[datetime]] = mapped_column(
        UTCDateTime(), comment="Automatic cookies: downloads use the cookies file until then",
    )
    check_frequency: Mapped[str] = mapped_column(
        default="default", server_default="default",
        comment="How often VODLoft looks for new episodes: default, less_often or own",
    )
    check_cron: Mapped[Optional[str]] = mapped_column(comment="The Collection's own schedule, with check_frequency own")
    membership_level: Mapped[str]
    type: Mapped[str]
    episode_identifier: Mapped[str]
    episode_order: Mapped[str] = mapped_column(
        default=_default_episode_order,
        comment="Which way the episodes are listed, within each season for a seasonal Collection: newest_first or oldest_first",
    )
    added_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), comment="Who added the Collection, for their own notifications",
    )
    author_name: Mapped[str]
    author_slug: Mapped[str]
    author_headshot_path: Mapped[Optional[str]]
    background_image_path: Mapped[Optional[str]] = mapped_column(comment=PICTURE_PATH_COMMENT)
    logo_image_path: Mapped[Optional[str]]
    thumbnail_landscape_path: Mapped[Optional[str]] = mapped_column(comment=PICTURE_PATH_COMMENT)
    thumbnail_portrait_path: Mapped[Optional[str]] = mapped_column(comment=PICTURE_PATH_COMMENT)
    thumbnail_square_path: Mapped[Optional[str]] = mapped_column(comment=PICTURE_PATH_COMMENT)
    open_count: Mapped[int] = mapped_column(
        default=0, server_default="0", comment="How often the Collection's page was opened",
    )
    last_opened_at: Mapped[Optional[datetime]] = mapped_column(
        UTCDateTime(), comment="When the Collection's page was last opened",
    )

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    site: Mapped[Optional["Site"]] = relationship(lazy="joined")
    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan", order_by="desc(Episode.index)"
    )
    seasons: Mapped[list["Season"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan", order_by="desc(Season.index)"
    )
    download_profiles: Mapped[list["DownloadProfile"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )
    stream_profiles: Mapped[list["StreamProfileBase"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )
    custom_index_states: Mapped[list["CustomIndexState"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Show(id={self.id}, slug={self.slug}, title={self.title}, created_at={self.created_at}, updated_at={self.updated_at})>"
