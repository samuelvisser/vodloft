from datetime import datetime
from typing import List, TYPE_CHECKING

from sqlalchemy import false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.datetime_types import UTCDateTime
from backend.types.media_types import MediaType

if TYPE_CHECKING:
    from backend.db.models.media_download import MediaDownloadBase


class MediaItemBase(Base):
    """Polymorphic VODLoft identity for a downloadable media placement."""

    __tablename__ = "media_items"
    __mapper_args__ = {
        "polymorphic_on": "type",
        "polymorphic_identity": MediaType.BASE.value,
    }

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(index=True, unique=True)
    source_key: Mapped[str] = mapped_column(index=True, comment="Id of the Source this comes from, as registered in sources")
    type: Mapped[str]
    drm_protected: Mapped[bool] = mapped_column(
        default=False, server_default=false(), comment="The media is protected by DRM and cannot be downloaded",
    )
    removed_from_source: Mapped[bool] = mapped_column(
        default=False, server_default=false(), comment="The Source no longer has the media; downloaded files are kept",
    )

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    downloads: Mapped[List["MediaDownloadBase"]] = relationship(
        back_populates="media", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<MediaItem(id={self.id}, type={self.type}, created_at={self.created_at}, updated_at={self.updated_at})>"
        )
