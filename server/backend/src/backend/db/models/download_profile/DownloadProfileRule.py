from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base

if TYPE_CHECKING:
    from .DownloadProfile import DownloadProfile


class DownloadProfileRule(Base):
    """One of your own lines in a Download Profile's Which episodes, after the built-in lines.

    Title and description rules match a regular expression anywhere in the text;
    duration rules compare the episode's length.
    """

    __tablename__ = "download_profile_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    download_profile_id: Mapped[int] = mapped_column(ForeignKey("download_profiles.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(comment="Order of the line within the profile, from 0")
    action: Mapped[str] = mapped_column(String(16), comment="skip, only or keep")
    field: Mapped[str] = mapped_column(String(16), comment="title, description or duration")
    pattern: Mapped[Optional[str]] = mapped_column(comment="The regular expression of a title or description rule")
    ignore_case: Mapped[bool] = mapped_column(default=False)
    duration_operator: Mapped[Optional[str]] = mapped_column(String(16), comment="shorter or longer, for a duration rule")
    duration_seconds: Mapped[Optional[int]]

    download_profile: Mapped["DownloadProfile"] = relationship(back_populates="rules")

    def __repr__(self) -> str:
        return f"<DownloadProfileRule(id={self.id}, action={self.action}, field={self.field})>"
