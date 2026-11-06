from typing import Optional

from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


class Site(Base):
    """A website VODLoft has collections or videos from, such as YouTube, whichever Source fetches them."""

    __tablename__ = "sites"

    key: Mapped[str] = mapped_column(primary_key=True, comment="The Site's key, as the sources package tells it")
    name: Mapped[str]
    domains: Mapped[list[str]] = mapped_column(JSON, default=list, comment="The domains of the Site VODLoft has seen")
    preferred_source_key: Mapped[Optional[str]] = mapped_column(
        comment="The Source asked first for links on this Site, when several Sources handle it",
    )
