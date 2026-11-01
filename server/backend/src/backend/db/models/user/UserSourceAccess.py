from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base

if TYPE_CHECKING:
    from .User import User


class UserSourceAccess(Base):
    """A Source a limited user may use, and the domains within it."""

    __tablename__ = "user_source_access"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    source_key: Mapped[str] = mapped_column(
        String(64), primary_key=True, comment="Id of the Source, as registered in sources",
    )
    domains: Mapped[Optional[list[str]]] = mapped_column(
        JSON, comment="Domains (and their subdomains) the user may use; null: all of the Source's domains",
    )

    user: Mapped["User"] = relationship(back_populates="source_access")
