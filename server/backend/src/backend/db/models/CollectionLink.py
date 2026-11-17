from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.datetime_types import UTCDateTime
from backend.types.collection_link_types import LinkPlacement

if TYPE_CHECKING:
    from backend.db.models import Collection, Season


class CollectionLink(Base):
    """One of the links a collection is indexed from, such as a channel's uploads or one of its playlists.

    A video several links list is kept once, by the link with the lowest ``position``.
    """

    __tablename__ = "collection_links"
    __table_args__ = (
        UniqueConstraint("collection_id", "url", name="uq_collection_link_url"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(comment="The link as the Source indexes it")
    title: Mapped[Optional[str]] = mapped_column(comment="The link's own title, the name of its season when it gets one")
    position: Mapped[int] = mapped_column(
        default=0, server_default="0", comment="Which link keeps a video several links list: the lowest",
    )
    placement: Mapped[str] = mapped_column(
        default=LinkPlacement.SITE_SEASONS.value, server_default=LinkPlacement.SITE_SEASONS.value,
        comment="Where the link's videos go: site_seasons, one_season or specials",
    )
    season_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("seasons.id", ondelete="SET NULL"), comment="The season of a one_season link, once it has one",
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    collection: Mapped["Collection"] = relationship(back_populates="links")
    season: Mapped[Optional["Season"]] = relationship()
    items: Mapped[list["CollectionLinkItem"]] = relationship(
        back_populates="link", cascade="all, delete-orphan", passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<CollectionLink(id={self.id}, collection_id={self.collection_id}, url={self.url!r}, position={self.position})>"


class CollectionLinkItem(Base):
    """A video a link listed, by the Source's own slug, so a link only looks up what it has not listed before."""

    __tablename__ = "collection_link_items"

    link_id: Mapped[int] = mapped_column(ForeignKey("collection_links.id", ondelete="CASCADE"), primary_key=True)
    source_slug: Mapped[str] = mapped_column(primary_key=True)

    link: Mapped["CollectionLink"] = relationship(back_populates="items")
