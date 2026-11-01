from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base

if TYPE_CHECKING:
    from .User import User


class UserAccess(Base):
    """A user's level for one area of VODLoft."""

    __tablename__ = "user_access"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    area: Mapped[str] = mapped_column(String(32), primary_key=True, comment="backend.security.access.Area")
    level: Mapped[str] = mapped_column(String(16), comment="none, view or manage")

    user: Mapped["User"] = relationship(back_populates="access")
