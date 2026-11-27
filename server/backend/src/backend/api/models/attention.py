"""Needs attention on Home."""
from __future__ import annotations

from datetime import datetime

from backend.api.models.base import ResponseBase
from backend.types.happenings import Happening, Severity


class AttentionRead(ResponseBase):
    """An open state: true until someone fixes or answers it."""

    id: int
    kind: Happening
    severity: Severity
    title: str
    body: str
    url: str | None
    collection_id: int | None
    opened_at: datetime
