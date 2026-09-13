from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    RETRY_SCHEDULED = "retry_scheduled"


class OperationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELED = "canceled"


class OperationSource(StrEnum):
    UI = "ui"
    API = "api"
    SYSTEM = "system"
    SCHEDULE = "schedule"
    EVENT = "event"


class TaskCancelled(RuntimeError):
    """Raised cooperatively by workers after a cancellation request."""


@dataclass(slots=True)
class TaskResult:
    result: Any = None
    message: str | None = None
