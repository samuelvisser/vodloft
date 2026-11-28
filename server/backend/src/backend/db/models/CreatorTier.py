
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


class CreatorTier(Base):
    """A paid tier a creator set up on a Site whose creators make their own tiers, such as a Patreon tier. Media that
    only patrons on the tier can watch points to it, so it stays with the tier when the creator renames it or changes
    its amount."""

    __tablename__ = "creator_tiers"
    __table_args__ = (UniqueConstraint("site_key", "site_tier_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    site_key: Mapped[str] = mapped_column(comment="The key of the Site the tier is on")
    site_tier_id: Mapped[str] = mapped_column(comment="The Site's own id of the tier")
    name: Mapped[str | None] = mapped_column(comment="What the creator calls the tier; None until VODLoft learns it")
    amount: Mapped[str | None] = mapped_column(comment='What the tier costs, as people write it, such as "$5"')
    rank: Mapped[int | None] = mapped_column(
        comment="Where the tier stands among the creator's tiers, such as its price in cents: a tier gives what a lower one gives",
    )
