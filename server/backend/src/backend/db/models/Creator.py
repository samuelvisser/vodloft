from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, ForeignKey, UniqueConstraint, false as sa_false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.datetime_types import UTCDateTime

if TYPE_CHECKING:
    from backend.db.models import Collection, Site


class Creator(Base):
    """Who made the work: a person or group, with an account on one or more Sites, and their collections.

    A creator never indexes or downloads anything itself. The sections of their accounts go into collections, which
    take them as links, and a collection from any other link can join them too.
    """

    __tablename__ = "creators"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(index=True, unique=True)
    slug: Mapped[str] = mapped_column(index=True, unique=True)
    title: Mapped[str]
    title_from_user: Mapped[bool] = mapped_column(
        default=False, server_default=sa_false(),
        comment="The name was changed in VODLoft, so the Site's name no longer replaces it",
    )
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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now(), onupdate=func.now())

    accounts: Mapped[list["CreatorAccount"]] = relationship(
        back_populates="creator", cascade="all, delete-orphan", order_by="CreatorAccount.id",
    )
    collections: Mapped[list["Collection"]] = relationship(back_populates="creator", foreign_keys="Collection.creator_id")

    @property
    def sections(self) -> list["CreatorSection"]:
        """The sections of all the creator's accounts."""
        return [section for account in self.accounts for section in account.sections]

    @property
    def main_collection_ids(self) -> set[int]:
        """The collections named after the creator, one for each account that has one."""
        return {account.main_collection_id for account in self.accounts if account.main_collection_id is not None}

    def __repr__(self) -> str:
        return f"<Creator(id={self.id}, slug={self.slug}, title={self.title!r})>"


class CreatorAccount(Base):
    """A creator's account on one Site, such as their YouTube channel or their page as a Daily Wire host."""

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
    main_collection_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL", use_alter=True),
        comment="The collection named after the creator that takes this account's uploads",
    )
    checked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), comment="When VODLoft last looked for new sections")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    creator: Mapped["Creator"] = relationship(back_populates="accounts")
    site: Mapped["Site"] = relationship(lazy="joined")
    sections: Mapped[list["CreatorSection"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", order_by="CreatorSection.site_position",
    )
    main_collection: Mapped[Optional["Collection"]] = relationship(foreign_keys=[main_collection_id], post_update=True)

    def __repr__(self) -> str:
        return f"<CreatorAccount(id={self.id}, creator_id={self.creator_id}, site_key={self.site_key}, site_ref={self.site_ref!r})>"


class CreatorSection(Base):
    """One part of a creator's account, such as its Videos, its Shorts or one of its playlists."""

    __tablename__ = "creator_sections"
    __table_args__ = (
        UniqueConstraint("account_id", "ref", name="uq_creator_section_ref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("creator_accounts.id", ondelete="CASCADE"), index=True)
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

    account: Mapped["CreatorAccount"] = relationship(back_populates="sections")

    def __repr__(self) -> str:
        return f"<CreatorSection(id={self.id}, account_id={self.account_id}, ref={self.ref!r}, kind={self.kind})>"
