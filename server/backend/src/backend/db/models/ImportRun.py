from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base
from backend.db.datetime_types import UTCDateTime


class ImportRun(Base):
    """One run of an importer: what it was asked to do, and what it did."""

    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    importer: Mapped[str] = mapped_column(String(32), index=True, comment="The importer's key, such as pinchflat")
    status: Mapped[str] = mapped_column(String(16), comment="running, waiting, finished or failed")
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, comment="What the person chose in the preview")
    uploaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), comment="When the imported upload was taken")
    version: Mapped[str | None] = mapped_column(String(64), comment="The other program's database version")
    report: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, comment="One entry per change and warning")
    counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now(), onupdate=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ImportLink(Base):
    """The ledger: what an import made of one thing of the other program, and what it wrote.

    ``written`` keeps a hash of each field as the import last wrote it, so a
    repeat run can tell a value the person changed in VODLoft (kept) from one
    only the other program changed (updated). ``unsupported`` keeps the
    settings the import could not map yet, so a later VODLoft maps them.
    """

    __tablename__ = "import_links"
    __table_args__ = (
        UniqueConstraint("importer", "kind", "external_id", name="uq_import_link_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    importer: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32), comment="profile, collection, download_profile or setting")
    external_id: Mapped[str] = mapped_column(String(255), comment="The other program's own id")
    entity_id: Mapped[int | None] = mapped_column(comment="The VODLoft row, by its id in the kind's table")
    written: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, comment="Field to hash of the value written")
    unsupported: Mapped[list[str]] = mapped_column(JSON, default=list, comment="Settings reported as not supported yet")
    run_id: Mapped[int | None] = mapped_column(ForeignKey("import_runs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now(), onupdate=func.now())


class ImportStep(Base):
    """The files of one imported Collection, adopted once its episodes are indexed."""

    __tablename__ = "import_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "collection_id", "local_media_profile_id", name="uq_import_step_scope"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("import_runs.id", ondelete="CASCADE"), index=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    local_media_profile_id: Mapped[int] = mapped_column(ForeignKey("local_media_profiles.id", ondelete="CASCADE"))
    download_profile_id: Mapped[int | None] = mapped_column(ForeignKey("download_profiles.id", ondelete="SET NULL"))
    enable_download_profile: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="Switch the Download Profile on once the files are adopted",
    )
    status: Mapped[str] = mapped_column(String(16), comment="waiting, done or failed")
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, comment="The planned files, as the plan has them")
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now(), onupdate=func.now())
