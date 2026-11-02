from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base
from backend.db.datetime_types import UTCDateTime


class ExistingFileScan(Base):
    """Files already on disk for one Collection and Local Media Profile, matched to episodes.

    One scan per pair: a new scan replaces the last. While a scan waits for a
    person to adopt its matches, the Download Profiles it holds stay off, so
    nothing is downloaded that is already there.
    """

    __tablename__ = "existing_file_scans"
    __table_args__ = (
        UniqueConstraint("collection_id", "local_media_profile_id", name="uq_existing_file_scan_scope"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    local_media_profile_id: Mapped[int] = mapped_column(
        ForeignKey("local_media_profiles.id", ondelete="CASCADE"), index=True,
    )
    folder: Mapped[str] = mapped_column(Text, comment="The scanned folder, as a /downloads/ path")
    template: Mapped[str | None] = mapped_column(Text, comment="The old layout's template, to read names with")
    status: Mapped[str] = mapped_column(String(16), comment="waiting, scanning, ready, failed or finished")
    error: Mapped[str | None] = mapped_column(Text)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    held_download_profile_ids: Mapped[list[int]] = mapped_column(
        JSON, default=list, comment="Download Profiles switched on again when the scan is finished",
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now(), onupdate=func.now())
