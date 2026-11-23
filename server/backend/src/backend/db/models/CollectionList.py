from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.datetime_types import UTCDateTime
from backend.types.link_season_types import ListStatus

if TYPE_CHECKING:
    from backend.db.models import Collection, Season


class CollectionList(Base):
    """A list of a collection: what a Site groups videos in, such as a YouTube playlist or an artist's album, of the
    channel the collection is made from. It is a season of the collection, or one of the lists of a season that holds
    several. A collection that only holds its lists' videos can also have lists the user added, from any Site, each
    read by the Source that handles its link.
    """

    __tablename__ = "collection_lists"
    __table_args__ = (
        UniqueConstraint("collection_id", "ref", name="uq_collection_list_ref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(comment="The Site's own id for the playlist")
    source_key: Mapped[str] = mapped_column(comment="Id of the Source that reads the list, as registered in sources")
    site_key: Mapped[Optional[str]] = mapped_column(ForeignKey("sites.key"), comment="The Site the list is on")
    url: Mapped[str]
    title: Mapped[str]
    image_path: Mapped[Optional[str]]
    item_count: Mapped[Optional[int]]
    site_position: Mapped[int] = mapped_column(default=0, server_default="0", comment="Where the Site lists it, newest first")
    enabled: Mapped[bool] = mapped_column(
        default=True, server_default="1", comment="Whether the playlist is a season, when only selected playlists are",
    )
    status: Mapped[str] = mapped_column(
        default=ListStatus.KNOWN.value, server_default=ListStatus.KNOWN.value,
        comment="known, or new while it waits for the user's choice",
    )
    as_season: Mapped[bool] = mapped_column(
        default=True, server_default="1",
        comment="Whether the list is a season of its own, or its videos join the collection's other seasons",
    )
    added_by_user: Mapped[bool] = mapped_column(
        default=False, server_default="0",
        comment="The user added the link, rather than it being one of the playlists of the collection's channel",
    )
    picture: Mapped[bool] = mapped_column(
        default=False, server_default="0",
        comment="Its picture is the collection's, for a collection without a link of its own; one at most per collection",
    )
    season_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("seasons.id", ondelete="SET NULL"), comment="The list's season, once it has one, which other lists of the collection may share",
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    collection: Mapped["Collection"] = relationship(back_populates="lists")
    season: Mapped[Optional["Season"]] = relationship()
    items: Mapped[list["CollectionListItem"]] = relationship(
        back_populates="list", cascade="all, delete-orphan", passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<CollectionList(id={self.id}, collection_id={self.collection_id}, ref={self.ref!r}, enabled={self.enabled})>"


class CollectionListItem(Base):
    """A video a list has, by the Source's own slug."""

    __tablename__ = "collection_list_items"

    list_id: Mapped[int] = mapped_column(ForeignKey("collection_lists.id", ondelete="CASCADE"), primary_key=True)
    source_slug: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(
        default=0, server_default="0", comment="Where the playlist lists the video, from 0: its order at its Site",
    )

    list: Mapped["CollectionList"] = relationship(back_populates="items")
