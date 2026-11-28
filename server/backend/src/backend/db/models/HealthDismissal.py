from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base
from backend.db.datetime_types import UTCDateTime


class HealthDismissal(Base):
    """A suggestion of the collection health check that the user put off or dismissed, such as grouping one creator's
    collections."""

    __tablename__ = "health_dismissals"
    __table_args__ = (UniqueConstraint("kind", "subject", name="uq_health_dismissal"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(comment="The check that made the suggestion, such as creators")
    subject: Mapped[str] = mapped_column(
        comment="What the suggestion is about, within its check, such as a creator's Site key and id: youtube:UC123",
    )
    until: Mapped[Optional[datetime]] = mapped_column(
        UTCDateTime(),
        comment="Until when it is put off, after which it shows again; null when dismissed for good",
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
