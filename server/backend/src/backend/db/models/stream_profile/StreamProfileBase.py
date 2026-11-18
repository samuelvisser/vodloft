from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import func, ForeignKey, JSON
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.db import Base
from backend.db.datetime_types import UTCDateTime
from backend.types.download_profile_types import EpIdType
from backend.types.stream_profile_types import StreamMediaKind, StreamProfileType
from backend.utils.helpers import generate_stream_profile_token

if TYPE_CHECKING:
    from backend.db.models import Collection


def _default_episode_types() -> list[str]:
    return [EpIdType.EP.value, EpIdType.AUX.value]


class StreamProfileBase(Base):
    __tablename__ = "stream_profiles"
    __mapper_args__ = {
        "polymorphic_on": "type",
        "polymorphic_identity": StreamProfileType.BASE.value,
    }

    # Whether an episode needs every media in ``media_kinds``, as an app gets an address for each (RSS);
    # a profile that plays one of them at a time needs only one.
    plays_every_media_kind = True
    # Whether the profile can stream episodes straight from their Site, and choose to pass that stream through
    # VODLoft; one that cannot only offers downloads.
    streams_from_site = True

    # Columns
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[str]
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"), index=True)
    overwrite_collection_title: Mapped[Optional[str]] = mapped_column(nullable=True, default=None)
    enable_profile: Mapped[bool] = mapped_column(default=True)
    # Secret path segment identifying this profile's feed/media routes. Stays
    # constant across edits to the (user-editable, purely informational)
    # feed_url so the feed keeps working even if that text is changed; can be
    # rotated via the regenerate-token endpoint to invalidate a leaked URL.
    token: Mapped[str] = mapped_column(
        unique=True, index=True, default=generate_stream_profile_token
    )

    use_downloads: Mapped[bool] = mapped_column(default=False, comment="Use local downloads for stream")
    use_source_stream: Mapped[bool] = mapped_column(default=False, comment="Stream episodes straight from their Source when the collection's Site can stream")
    preferred_format: Mapped[str] = mapped_column(comment="Preferred format for stream, used when choosing the correct downloaded file "
                                                          "or whether to stream audio or video from DW")
    prefer_exact_match: Mapped[bool] = mapped_column(comment="Stream from Daily Wire if the exact resolution the stream profile prefers is not available locally (even if another resolution is)")
    ep_id_type_list: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=_default_episode_types,
        server_default='["ep", "aux"]',
        nullable=False,
    )

    max_items: Mapped[int] = mapped_column(default=0, server_default="0", comment="The most episodes offered, newest first; 0 offers every one")
    stream_live_episodes: Mapped[bool] = mapped_column(default=False, server_default="0", nullable=False)
    proxy_source_stream: Mapped[bool] = mapped_column(
        default=True, server_default="1", nullable=False,
        comment="Pass the Site's stream on through VODLoft instead of sending apps to the Site",
    )
    # Live episodes played from the Site that stay playable from there until their final download lands.
    live_episode_handoff_ids: Mapped[list[int]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        server_default="[]",
        nullable=False,
    )

    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None,
        comment="The user whose feed this is; only they and those who manage every Stream Profile see it",
    )

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    collection: Mapped["Collection"] = relationship(back_populates="stream_profiles")


    @property
    def media_kinds(self) -> tuple[StreamMediaKind, ...]:
        """What the profile serves of each episode, its main media first."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<StreamProfileBase(id={self.id}, enable_profile={self.enable_profile}, use_downloads={self.use_downloads}, use_source_stream={self.use_source_stream}, created_at={self.created_at}, updated_at={self.updated_at})>"