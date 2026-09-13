from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base
from backend.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from backend.db.models import TaskDefinition


class TaskSchedule(Base, TimestampMixin):
    __tablename__ = "task_schedules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("task_definitions.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32), default="user", index=True)
    registry_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    resource_type: Mapped[str] = mapped_column(String(32), default="system", index=True)
    resource_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), default="cron")
    trigger_args: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    coalesce: Mapped[bool] = mapped_column(Boolean, default=True)
    max_retries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_run_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    definition: Mapped["TaskDefinition"] = relationship("TaskDefinition", lazy="joined")
