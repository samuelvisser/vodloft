from __future__ import annotations

from sqlalchemy import Boolean, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base
from backend.db.mixins import TimestampMixin


class TaskDefinition(Base, TimestampMixin):
    __tablename__ = "task_definitions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    allowed_resource_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_max_retries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tracks_progress: Mapped[bool] = mapped_column(Boolean, default=True)
