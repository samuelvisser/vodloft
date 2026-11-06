from typing import Optional

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base
from backend.types.site_types import (
    PENDING_LIVE_MINUTES,
    PENDING_STARTING_MINUTES,
    PENDING_UPCOMING_MINUTES,
    SiteRefreshMode,
)


class Site(Base):
    """A website VODLoft has collections or videos from, such as YouTube, whichever Source fetches them."""

    __tablename__ = "sites"

    key: Mapped[str] = mapped_column(primary_key=True, comment="The Site's key, as the sources package tells it")
    name: Mapped[str]
    domains: Mapped[list[str]] = mapped_column(JSON, default=list, comment="The domains of the Site VODLoft has seen")
    preferred_source_key: Mapped[Optional[str]] = mapped_column(
        comment="The Source asked first for links on this Site, when several Sources handle it",
    )
    refresh_mode: Mapped[str] = mapped_column(
        String, default=SiteRefreshMode.SYSTEM.value, server_default=SiteRefreshMode.SYSTEM.value,
        comment="Which schedule the Site's items follow while their metadata is looked up again: off, system or own",
    )
    refresh_intervals: Mapped[Optional[str]] = mapped_column(
        comment="The Site's own refresh schedule, such as 30m,2h,24h, used when refresh_mode is own",
    )
    pending_checks: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1",
        comment="Whether upcoming and live videos are added and followed until they are published",
    )
    pending_upcoming_minutes: Mapped[int] = mapped_column(
        Integer, default=PENDING_UPCOMING_MINUTES, server_default=str(PENDING_UPCOMING_MINUTES),
        comment="Minutes between lookups of an upcoming episode",
    )
    pending_starting_minutes: Mapped[int] = mapped_column(
        Integer, default=PENDING_STARTING_MINUTES, server_default=str(PENDING_STARTING_MINUTES),
        comment="Minutes between lookups from 15 minutes before an episode starts until an hour after",
    )
    pending_live_minutes: Mapped[int] = mapped_column(
        Integer, default=PENDING_LIVE_MINUTES, server_default=str(PENDING_LIVE_MINUTES),
        comment="Minutes between lookups while an episode is live or still being finished",
    )
