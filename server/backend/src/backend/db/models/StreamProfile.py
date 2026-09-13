from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from backend.db.models import Collection


class StreamProfile(Base, TimestampMixin):
    __tablename__ = "stream_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    enable_profile: Mapped[bool] = mapped_column(Boolean, default=True)
    use_downloads: Mapped[bool] = mapped_column(Boolean, default=False)
    format_selector: Mapped[str] = mapped_column(
        Text,
        default="best[protocol^=http][vcodec!=none][acodec!=none]/best",
    )

    collection: Mapped["Collection | None"] = relationship(
        "Collection",
        back_populates="stream_profiles",
    )
