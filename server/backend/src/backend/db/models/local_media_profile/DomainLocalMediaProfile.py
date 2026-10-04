from sqlalchemy import ForeignKey, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from backend.types.local_media_profile_types import LocalMediaProfileType
from .LocalMediaProfileBase import LocalMediaProfileBase


class DomainLocalMediaProfile(LocalMediaProfileBase):
    """A Source-independent local representation for one content Domain."""

    __tablename__ = "local_media_profiles_domain"
    __mapper_args__ = {"polymorphic_identity": LocalMediaProfileType.DOMAIN.value}

    id: Mapped[int] = mapped_column(ForeignKey("local_media_profiles.id", ondelete="CASCADE"), primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("vodloft_domains.id"), nullable=False)
    applicable_kinds: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["video", "movie", "movie_extra"], nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    delivery_target_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    representation: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    impairment: Mapped[str | None] = mapped_column(nullable=True)
