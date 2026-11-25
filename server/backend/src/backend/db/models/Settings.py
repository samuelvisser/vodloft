from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, String, Text, false, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base
from backend.db.datetime_types import UTCDateTime
from backend.utils.helpers import generate_stream_profile_token


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
    )
    health_checks_off: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]", nullable=False,
        comment="The checks of the collection health check that the user turned off, by kind, such as creators",
    )
    user_accounts_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
        comment="Everyone signs in with their own account instead of the one shared password",
    )
    ytdlp_options: Mapped[str] = mapped_column(
        Text, default="", server_default="", nullable=False,
        comment="Your own yt-dlp options for every download of the yt-dlp Source, one or more per line",
    )
    stream_token: Mapped[str] = mapped_column(
        String(64), default=generate_stream_profile_token,
        comment="Secret in the addresses of the playlist and guide with every channel, for an install without user accounts",
    )
    api_key_note_after: Mapped[Optional[datetime]] = mapped_column(
        UTCDateTime(), nullable=True,
        comment="Until when Home does not ask for an API key, after Remind me later",
    )
    api_key_note_off: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False,
        comment="Home never asks for an API key",
    )
    alembic_version_num: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )
    background_migration_version: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self):
        return (
            f"<Settings(id={self.id}, onboarding_completed={self.onboarding_completed}, "
            f"alembic_version_num={self.alembic_version_num}, "
            f"background_migration_version={self.background_migration_version}, "
            f"created_at={self.created_at}, updated_at={self.updated_at})>"
        )
