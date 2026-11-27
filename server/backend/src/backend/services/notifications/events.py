"""Recording that something happened: an event, of a kind from ``backend.types.happenings``.

``emit`` stores the event and the deliveries every matching rule asks for, in the caller's transaction, so the
event is only sent once whatever caused it is committed. Sending happens later, in the background.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.db.models import NotificationEvent as EventRow
from backend.types.happenings import DEFINITIONS, Happening


def emit(
    session: Session,
    happening: Happening,
    *,
    title: str,
    body: str = "",
    collection_id: int | None = None,
    user_id: int | None = None,
    url: str | None = None,
    data: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    occurred_at: datetime | None = None,
) -> EventRow:
    """Record that something happened, and queue it for every rule that wants it."""
    from .delivery import enqueue

    row = EventRow(
        event=happening.value, severity=DEFINITIONS[happening].severity.value,
        occurred_at=occurred_at or datetime.now(timezone.utc), collection_id=collection_id, user_id=user_id, title=title[:255], body=body, url=url, data=data or {}, dedupe_key=dedupe_key,
    )
    session.add(row)
    session.flush()
    enqueue(session, row)
    return row
