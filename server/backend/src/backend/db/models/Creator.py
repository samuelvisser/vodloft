from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.datetime_types import UTCDateTime

if TYPE_CHECKING:
    from backend.db.models import Collection, Movie, Site


class Creator(Base):
    """Who made the work: a person or group, with an account on one or more Sites. A creator groups their channel
    collections and movies in the Library, and plays no part in what a collection holds."""

    __tablename__ = "creators"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(index=True, unique=True)
    slug: Mapped[str] = mapped_column(index=True, unique=True)
    title: Mapped[str]
    description: Mapped[Optional[str]]
    avatar_path: Mapped[Optional[str]]
    banner_path: Mapped[Optional[str]]
    links: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]", comment="The creator's own links")
    facts: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]", comment='Short facts, such as "1.2M subscribers"')
    added_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    genre: Mapped[Optional[str]] = mapped_column(comment="Given to the creator's collections, for their NFO files")
    content_rating: Mapped[Optional[str]] = mapped_column(comment="Given to the creator's collections, for their NFO files")
    open_count: Mapped[int] = mapped_column(
        default=0, server_default="0", comment="How often the creator's page was opened",
    )
    last_opened_at: Mapped[Optional[datetime]] = mapped_column(
        UTCDateTime(), comment="When the creator's page was last opened",
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now(), onupdate=func.now())

    accounts: Mapped[list["CreatorAccount"]] = relationship(
        back_populates="creator", cascade="all, delete-orphan", order_by="CreatorAccount.id",
    )
    collections: Mapped[list["Collection"]] = relationship(back_populates="creator", foreign_keys="Collection.creator_id")
    movies: Mapped[list["Movie"]] = relationship(back_populates="creator", foreign_keys="Movie.creator_id")

    def __repr__(self) -> str:
        return f"<Creator(id={self.id}, slug={self.slug}, title={self.title!r})>"


class CreatorAccount(Base):
    """A creator's account on one Site, such as their YouTube channel or their page as a Daily Wire host: where their
    page looks up what else they have."""

    __tablename__ = "creator_accounts"
    __table_args__ = (
        UniqueConstraint("site_key", "site_ref", name="uq_creator_account_site_ref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"), index=True)
    source_key: Mapped[str] = mapped_column(comment="Id of the Source that looks the account up")
    site_key: Mapped[str] = mapped_column(ForeignKey("sites.key"), index=True)
    site_ref: Mapped[str] = mapped_column(comment="The Site's own id for the account")
    url: Mapped[Optional[str]] = mapped_column(comment="The account's page; empty when the Site has none, such as a Daily Wire host")
    handle: Mapped[Optional[str]]
    avatar_path: Mapped[Optional[str]] = mapped_column(comment="The account's own picture on its Site")
    banner_path: Mapped[Optional[str]] = mapped_column(comment="The account's own banner on its Site")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    creator: Mapped["Creator"] = relationship(back_populates="accounts")
    site: Mapped["Site"] = relationship(lazy="joined")

    def __repr__(self) -> str:
        return f"<CreatorAccount(id={self.id}, creator_id={self.creator_id}, site_key={self.site_key}, site_ref={self.site_ref!r})>"
