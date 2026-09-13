from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from backend.db.models import Collection, LocalMediaProfile


class DownloadProfile(Base, TimestampMixin):
    __tablename__ = "download_profiles"
    __table_args__ = (
        UniqueConstraint(
            "collection_id",
            "local_media_profile_id",
            name="uq_download_profile_collection_media",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    local_media_profile_id: Mapped[int] = mapped_column(ForeignKey("local_media_profiles.id"))
    enable_profile: Mapped[bool] = mapped_column(Boolean, default=True)

    collection: Mapped["Collection | None"] = relationship(
        "Collection",
        back_populates="download_profiles",
    )
    local_media_profile: Mapped["LocalMediaProfile"] = relationship(
        "LocalMediaProfile",
        back_populates="download_profiles",
        lazy="joined",
    )
