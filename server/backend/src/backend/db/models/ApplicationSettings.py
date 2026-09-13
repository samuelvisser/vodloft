from __future__ import annotations

import secrets

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base
from backend.db.mixins import TimestampMixin


class ApplicationSettings(Base, TimestampMixin):
    __tablename__ = "application_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    alembic_version_num: Mapped[str | None] = mapped_column(String(64), nullable=True)
    auth_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_username: Mapped[str] = mapped_column(String(128), default="admin")
    admin_password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_secret: Mapped[str] = mapped_column(
        String(255),
        default=lambda: secrets.token_urlsafe(48),
    )
    rss_token: Mapped[str] = mapped_column(
        String(255),
        default=lambda: secrets.token_urlsafe(32),
        unique=True,
    )
    rss_item_limit: Mapped[int] = mapped_column(Integer, default=200)
