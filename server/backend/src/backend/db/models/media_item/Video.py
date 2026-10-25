from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.datetime_types import UTCDateTime
from backend.db.mixins.MediaContentMetadataMixin import MediaContentMetadataMixin
from backend.types.media_types import MediaType

from .MediaItemBase import MediaItemBase


class Video(MediaItemBase, MediaContentMetadataMixin):
    """A single video added on its own, outside any show."""

    __tablename__ = "media_items_video"
    __mapper_args__ = {"polymorphic_identity": MediaType.VIDEO.value, "polymorphic_load": "selectin"}

    id: Mapped[int] = mapped_column(ForeignKey("media_items.id", ondelete="CASCADE"), primary_key=True)
    # The Source's own id for the video. It is unique within one Source, which
    # the videos service checks, since source_key lives on media_items.
    slug: Mapped[str] = mapped_column(index=True)
    sharing_url: Mapped[str]
    author_name: Mapped[Optional[str]]
    author_url: Mapped[Optional[str]]
    published_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())

    def __repr__(self) -> str:
        return f"<Video(id={self.id}, source_key={self.source_key}, slug={self.slug}, title={self.title})>"
