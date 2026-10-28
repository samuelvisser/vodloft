from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, BigInteger, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base
from backend.db.datetime_types import UTCDateTime


class QuickDownloadHistory(Base):
    """One quick download as it is remembered: what, from where, as what, and how it ended.

    It holds no file path and no link to any media row. The file itself lives
    only in the temporary folder, and only until it has been downloaded.
    """

    __tablename__ = "quick_download_history"
    __table_args__ = (Index("ix_quick_download_history_started_at", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quick_download_id: Mapped[str] = mapped_column(unique=True, comment="Id of the quick download's ready folder")
    title: Mapped[str]
    source_key: Mapped[str] = mapped_column(comment="Id of the Source, as registered in sources")
    source_name: Mapped[str]
    url: Mapped[str]
    format: Mapped[str] = mapped_column(comment="The choice as people read it, such as 'Video · 1080p MP4'")
    choice: Mapped[dict] = mapped_column(JSON, comment="The choice, to download it again the same way")
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    outcome: Mapped[str] = mapped_column(
        comment="working, ready, downloaded, expired, discarded, canceled, failed or refused",
    )
    message: Mapped[Optional[str]] = mapped_column(comment="Why it failed or was refused")
    owner: Mapped[Optional[str]] = mapped_column(comment="The user who asked for it, once VODLoft has users")
