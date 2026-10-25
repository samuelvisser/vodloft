from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from backend.types.media_types import MediaType

from .MediaDownloadBase import MediaDownloadBase


class VideoMediaDownload(MediaDownloadBase):
    __tablename__ = "media_downloads_video"
    __mapper_args__ = {"polymorphic_identity": MediaType.VIDEO.value}

    id: Mapped[int] = mapped_column(
        ForeignKey("media_downloads.id", ondelete="CASCADE"),
        primary_key=True,
    )
