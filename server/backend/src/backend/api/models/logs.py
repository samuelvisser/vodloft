from __future__ import annotations

from datetime import datetime
from typing import Literal

from backend.api.models.base import ResponseBase


class ApplicationLogEntryRead(ResponseBase):
    id: int
    timestamp: datetime
    level: str
    logger: str
    message: str
    exception: str | None = None


class ApplicationLogPageRead(ResponseBase):
    items: list[ApplicationLogEntryRead]
    total: int
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    has_older: bool
    has_newer: bool
    retained_limit: int
