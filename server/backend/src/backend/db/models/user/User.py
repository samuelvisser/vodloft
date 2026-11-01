from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, String, false, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.datetime_types import UTCDateTime

if TYPE_CHECKING:
    from .UserAccess import UserAccess
    from .UserSourceAccess import UserSourceAccess


class User(Base):
    """A person who signs in to VODLoft once user accounts are on.

    Its access is one row per area in ``user_access``. With ``all_sources``
    off, it may only use the Sources listed in ``user_source_access``.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(
        String(64, collation="NOCASE"), unique=True,
        comment="Sign-in name; unique regardless of upper or lower case",
    )
    password_hash: Mapped[str] = mapped_column(
        comment="scrypt over the value the browser derives from the password",
    )
    is_enabled: Mapped[bool] = mapped_column(default=True, server_default=true())
    must_change_password: Mapped[bool] = mapped_column(
        default=True, server_default=true(),
        comment="Set by an administrator's first or reset password; cleared when the user picks their own",
    )
    session_version: Mapped[int] = mapped_column(
        default=1, server_default="1",
        comment="Sessions carry this number; raising it signs the user out everywhere",
    )
    template_key: Mapped[Optional[str]] = mapped_column(
        comment="The template the access list was filled in from, as long as it still matches",
    )
    all_sources: Mapped[bool] = mapped_column(
        default=True, server_default=true(),
        comment="Off: only the Sources in user_source_access",
    )
    members_only: Mapped[bool] = mapped_column(
        default=False, server_default=false(),
        comment="May use media that needs the install's Source memberships",
    )
    delete_files: Mapped[bool] = mapped_column(
        default=False, server_default=false(),
        comment="May delete downloaded files from disk",
    )
    created_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    last_login_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())

    access: Mapped[list["UserAccess"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin",
    )
    source_access: Mapped[list["UserSourceAccess"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin",
    )
    created_by: Mapped[Optional["User"]] = relationship(remote_side=[id])

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username!r}, is_enabled={self.is_enabled})>"
