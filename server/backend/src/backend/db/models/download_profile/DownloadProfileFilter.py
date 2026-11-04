from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base

if TYPE_CHECKING:
    from .DownloadProfile import DownloadProfile


class DownloadProfileFilter(Base):
    """One line of a Download Profile's Which episodes.

    The lines are applied in order: each one only sees the episodes the lines above it
    let through. Each field stores only the settings it needs; the rest stay empty.
    """

    __tablename__ = "download_profile_filters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    download_profile_id: Mapped[int] = mapped_column(ForeignKey("download_profiles.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(comment="Order of the line within the profile, from 0")
    action: Mapped[str] = mapped_column(String(16), comment="skip, only or keep")
    field: Mapped[str] = mapped_column(
        String(16), comment="title, description, duration, types, seasons, published or downloaded",
    )
    pattern: Mapped[Optional[str]] = mapped_column(
        comment="The regular expression of a title or description line; a leading (?i) ignores case",
    )
    duration_operator: Mapped[Optional[str]] = mapped_column(String(16), comment="shorter or longer, for a duration line")
    duration_seconds: Mapped[Optional[int]]
    episode_types: Mapped[Optional[list[str]]] = mapped_column(JSON, comment="The episode type keys of a types line")
    season_slugs: Mapped[Optional[list[str]]] = mapped_column(JSON, comment="The season slugs of a seasons line")
    include_upcoming: Mapped[bool] = mapped_column(
        default=False, server_default="0", comment="A seasons line adds each new season to its slugs",
    )
    days: Mapped[Optional[int]] = mapped_column(comment="A published or downloaded line: the last N days")
    count: Mapped[Optional[int]] = mapped_column(comment="A published line: the latest N episodes")
    starting_from: Mapped[Optional[date]] = mapped_column(Date, comment="A published line: published since this day")

    download_profile: Mapped["DownloadProfile"] = relationship(back_populates="filters")

    def __repr__(self) -> str:
        return f"<DownloadProfileFilter(id={self.id}, action={self.action}, field={self.field})>"
