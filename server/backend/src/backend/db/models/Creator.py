from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.datetime_types import UTCDateTime

if TYPE_CHECKING:
    from backend.db.models import Collection, Site


class Creator(Base):
    """A creator on one Site: who made the work, and the sections their page offers.

    A creator never indexes or downloads anything itself. Its sections go into collections, which take them as links.
    """

    __tablename__ = "creators"
    __table_args__ = (
        UniqueConstraint("site_key", "site_ref", name="uq_creator_site_ref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(index=True, unique=True)
    slug: Mapped[str] = mapped_column(index=True, unique=True)
    source_key: Mapped[str] = mapped_column(comment="Id of the Source that looks the creator up")
    site_key: Mapped[str] = mapped_column(ForeignKey("sites.key"), index=True)
    site_ref: Mapped[str] = mapped_column(comment="The Site's own id for the creator")
    url: Mapped[Optional[str]] = mapped_column(comment="The creator's page; empty when the Site has none, such as a Daily Wire host")
    title: Mapped[str]
    handle: Mapped[Optional[str]]
    description: Mapped[Optional[str]]
    avatar_path: Mapped[Optional[str]]
    banner_path: Mapped[Optional[str]]
    links: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]", comment="The creator's own links")
    facts: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]", comment='Short facts, such as "1.2M subscribers"')
    added_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    new_sections: Mapped[str] = mapped_column(
        default="ask", server_default="ask", comment="What happens when the creator adds a section: ask, season, own or ignore",
    )
    genre: Mapped[Optional[str]] = mapped_column(comment="Given to the creator's collections, for their NFO files")
    content_rating: Mapped[Optional[str]] = mapped_column(comment="Given to the creator's collections, for their NFO files")
    main_collection_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL", use_alter=True), comment="The collection named after the creator",
    )
    checked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), comment="When VODLoft last looked for new sections")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now(), onupdate=func.now())

    site: Mapped["Site"] = relationship(lazy="joined")
    sections: Mapped[list["CreatorSection"]] = relationship(
        back_populates="creator", cascade="all, delete-orphan", order_by="CreatorSection.site_position",
    )
    collections: Mapped[list["Collection"]] = relationship(back_populates="creator", foreign_keys="Collection.creator_id")
    main_collection: Mapped[Optional["Collection"]] = relationship(foreign_keys=[main_collection_id], post_update=True)

    def __repr__(self) -> str:
        return f"<Creator(id={self.id}, slug={self.slug}, site_key={self.site_key}, title={self.title!r})>"


class CreatorSection(Base):
    """One part of a creator, such as its Videos, its Shorts or one of its playlists."""

    __tablename__ = "creator_sections"
    __table_args__ = (
        UniqueConstraint("creator_id", "ref", name="uq_creator_section_ref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(comment="The Site's own id for the section")
    url: Mapped[str]
    title: Mapped[str]
    kind: Mapped[str] = mapped_column(comment="feed, list, show or item")
    role: Mapped[str] = mapped_column(default="main", server_default="main", comment="main, short or live")
    kind_label: Mapped[Optional[str]] = mapped_column(comment="What the Site calls it, such as Playlist")
    item_count: Mapped[Optional[int]]
    image_path: Mapped[Optional[str]]
    description: Mapped[Optional[str]]
    access: Mapped[Optional[str]] = mapped_column(comment="The key of the access the section needs")
    site_position: Mapped[int] = mapped_column(default=0, server_default="0", comment="Where the Site lists it")
    status: Mapped[str] = mapped_column(
        default="known", server_default="known",
        comment="known; new, found by the daily look and waiting for a choice; or ignored",
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    creator: Mapped["Creator"] = relationship(back_populates="sections")

    def __repr__(self) -> str:
        return f"<CreatorSection(id={self.id}, creator_id={self.creator_id}, ref={self.ref!r}, kind={self.kind})>"
