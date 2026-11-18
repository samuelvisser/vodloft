from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.datetime_types import UTCDateTime
from backend.types.link_season_types import LinkSeasonStatus

if TYPE_CHECKING:
    from backend.db.models import Collection, Season


class LinkSeason(Base):
    """A link season: a list of the channel a collection is made from, such as a YouTube playlist or an artist's
    album, which can be a season of the collection. A collection that only holds its link seasons' videos can also
    have links the user added, from any Site its Source fetches.
    """

    __tablename__ = "link_seasons"
    __table_args__ = (
        UniqueConstraint("collection_id", "ref", name="uq_link_season_ref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(comment="The Site's own id for the playlist")
    url: Mapped[str]
    title: Mapped[str]
    image_path: Mapped[Optional[str]]
    item_count: Mapped[Optional[int]]
    site_position: Mapped[int] = mapped_column(default=0, server_default="0", comment="Where the Site lists it, newest first")
    enabled: Mapped[bool] = mapped_column(
        default=True, server_default="1", comment="Whether the playlist is a season, when only selected playlists are",
    )
    status: Mapped[str] = mapped_column(
        default=LinkSeasonStatus.KNOWN.value, server_default=LinkSeasonStatus.KNOWN.value,
        comment="known, or new while it waits for the user's choice",
    )
    added_by_user: Mapped[bool] = mapped_column(
        default=False, server_default="0",
        comment="The user added the link, rather than it being one of the playlists of the collection's channel",
    )
    season_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("seasons.id", ondelete="SET NULL"), comment="The playlist's season, once it has one",
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    collection: Mapped["Collection"] = relationship(back_populates="season_links")
    season: Mapped[Optional["Season"]] = relationship()
    items: Mapped[list["LinkSeasonItem"]] = relationship(
        back_populates="link_season", cascade="all, delete-orphan", passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<LinkSeason(id={self.id}, collection_id={self.collection_id}, ref={self.ref!r}, enabled={self.enabled})>"


class LinkSeasonItem(Base):
    """A video a playlist lists, by the Source's own slug."""

    __tablename__ = "link_season_items"

    link_season_id: Mapped[int] = mapped_column(ForeignKey("link_seasons.id", ondelete="CASCADE"), primary_key=True)
    source_slug: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(
        default=0, server_default="0", comment="Where the playlist lists the video, from 0: its order at its Site",
    )

    link_season: Mapped["LinkSeason"] = relationship(back_populates="items")
