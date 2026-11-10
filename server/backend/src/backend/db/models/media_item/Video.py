from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.datetime_types import UTCDateTime
from backend.db.mixins.MediaContentMetadataMixin import MediaContentMetadataMixin
from backend.db.mixins.CreatedByMixin import CreatedByMixin
from backend.types.media_types import MediaType

from .MediaItemBase import MediaItemBase

if TYPE_CHECKING:
    from backend.db.models import Site


class Video(MediaItemBase, MediaContentMetadataMixin, CreatedByMixin):
    """A single video added on its own, outside any collection."""

    __tablename__ = "media_items_video"
    __mapper_args__ = {"polymorphic_identity": MediaType.VIDEO.value, "polymorphic_load": "selectin"}

    id: Mapped[int] = mapped_column(ForeignKey("media_items.id", ondelete="CASCADE"), primary_key=True)
    # The Source's own id for the video. It is unique within one Source, which
    # the videos service checks, since source_key lives on media_items.
    slug: Mapped[str] = mapped_column(index=True)
    sharing_url: Mapped[str]
    site_key: Mapped[Optional[str]] = mapped_column(
        ForeignKey("sites.key"), index=True, comment="The Site the video is on; filled in the background for older videos",
    )
    author_name: Mapped[Optional[str]]
    author_url: Mapped[Optional[str]]
    published_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    metadata_is_final: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1",
        comment="False while VODLoft still looks the video up again after publication",
    )
    metadata_refreshed_at: Mapped[Optional[datetime]] = mapped_column(
        UTCDateTime(), comment="When VODLoft last looked the video up at its Source, by a refresh or a manual Refresh now",
    )

    site: Mapped[Optional["Site"]] = relationship(lazy="joined")

    def __repr__(self) -> str:
        return f"<Video(id={self.id}, source_key={self.source_key}, slug={self.slug}, title={self.title})>"
