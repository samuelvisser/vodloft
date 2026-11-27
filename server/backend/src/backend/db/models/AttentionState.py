"""What is true until someone fixes or answers it, such as a destination that keeps failing.

Home shows the open ones under Needs attention. See ``backend.types.happenings`` for the kinds and
``backend.services.attention`` for opening and resolving them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base
from backend.db.datetime_types import UTCDateTime
from backend.types.happenings import DEFINITIONS, Happening, Severity


class AttentionState(Base):
    __tablename__ = "attention_states"
    __table_args__ = (
        # One open state per kind and subject: while it stays open, finding it again only refreshes it.
        Index(
            "uq_attention_states_open", "kind", "subject_key", unique=True,
            sqlite_where=text("resolved_at IS NULL"), postgresql_where=text("resolved_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), comment="Its kind in the happenings registry")
    subject_key: Mapped[str] = mapped_column(
        String(128), comment="What it is about, such as destination:4 or task:collection_health",
    )
    collection_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True, comment="The collection it is about, if any",
    )
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[Optional[str]] = mapped_column(String(512), comment="Where in VODLoft to fix it")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime())
    put_off_until: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), comment="Hidden from Home until then")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), index=True)

    @property
    def severity(self) -> Severity:
        return DEFINITIONS[Happening(self.kind)].severity
