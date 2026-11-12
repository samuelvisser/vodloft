from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.datetime_types import UTCDateTime
from .MediaDownloadBase import MediaDownloadBase
from backend.types.media_types import MediaType

if TYPE_CHECKING:
    from backend.db.models import DownloadProfile


class EpisodeMediaDownload(MediaDownloadBase):
    __tablename__ = "media_downloads_episode"
    __mapper_args__ = {"polymorphic_identity": MediaType.EPISODE.value}

    # Columns
    id: Mapped[int] = mapped_column(ForeignKey("media_downloads.id", ondelete="CASCADE"), primary_key=True)
    download_profile_id: Mapped[Optional[int]] = mapped_column(ForeignKey("download_profiles.id", ondelete="SET NULL"), index=True)
    downloaded_publish_status: Mapped[Optional[str]]
    redownload_when_final: Mapped[bool] = mapped_column(default=False)
    redownload_when_delay_passed: Mapped[bool] = mapped_column(default=False)
    kept: Mapped[bool] = mapped_column(
        default=False, server_default="0", comment="Kept by hand: retention never deletes this download"
    )

    upgrade_checks: Mapped[int] = mapped_column(
        default=0, server_default="0", comment="How many times the upgrade check has looked at this download",
    )
    upgrade_check_at: Mapped[Optional[datetime]] = mapped_column(
        UTCDateTime(), comment="When the upgrade check looks next; empty when it will not",
    )
    upgrade_result: Mapped[Optional[str]] = mapped_column(
        String(16), comment="What the last upgrade check found: upgraded or checked",
    )

    # Relationships
    download_profile: Mapped[Optional["DownloadProfile"]] = relationship(back_populates="episode_downloads")

    def __repr__(self) -> str:
        return (
            f"<EpisodeMediaDownload(id={self.id}, download_profile_id={self.download_profile_id}, "
            f"artifact_status={self.artifact_status})>"
        )
