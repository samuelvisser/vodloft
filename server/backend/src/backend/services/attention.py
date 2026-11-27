"""What needs attention: states that stay open until whatever found them no longer does.

A check calls ``open_state`` when it finds something and ``resolve_state`` when it no longer does, inside its write
transaction. While a state stays open, finding it again only refreshes its text, so a broken Plex is one item on
Home and one message, not one per download. A state that really opens also sends an event of its kind: that is the
one place Home and messages meet. A resolved state simply disappears from Home.

Every function only writes what changed, so a check that finds the same as last time stays a read for
``write_when_changed``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.db.models import AttentionState, Collection
from backend.security.access import Access
from backend.types.happenings import DEFINITIONS, Happening, Severity, Shape

SEVERITY_ORDER = (Severity.PROBLEM, Severity.NEEDS_YOU, Severity.TIP)
"""How Home lists open states: problems first. News never opens a state."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _open(session: Session, kind: Happening, subject_key: str) -> AttentionState | None:
    return session.scalar(select(AttentionState).where(
        AttentionState.kind == kind.value, AttentionState.subject_key == subject_key,
        AttentionState.resolved_at.is_(None),
    ))


def is_open(session: Session, kind: Happening, subject_key: str) -> bool:
    return _open(session, kind, subject_key) is not None


def _set(row: AttentionState, **values: Any) -> None:
    for name, value in values.items():
        if getattr(row, name) != value:
            setattr(row, name, value)


def open_state(
    session: Session,
    kind: Happening,
    subject_key: str,
    *,
    title: str,
    body: str = "",
    url: str | None = None,
    collection_id: int | None = None,
    data: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> AttentionState:
    """Open a state of ``kind`` about ``subject_key``, or refresh the one that is open.

    Only a state that really opens sends its event; a refresh sends nothing.
    """
    definition = DEFINITIONS[kind]
    if definition.shape != Shape.STATE:
        raise ValueError(f"{kind} is an event, not a state")
    title = title[:255]
    row = _open(session, kind, subject_key)
    if row is not None:
        _set(row, title=title, body=body, url=url, collection_id=collection_id, data=data or {})
        return row
    from backend.services.notifications.events import emit

    now = now or _now()
    row = AttentionState(
        kind=kind.value, subject_key=subject_key, collection_id=collection_id, title=title, body=body, url=url,
        data=data or {}, opened_at=now,
    )
    session.add(row)
    session.flush()
    emit(session, kind, title=title, body=body, url=url, collection_id=collection_id, data=data, occurred_at=now)
    return row


def resolve_state(session: Session, kind: Happening, subject_key: str, *, now: datetime | None = None) -> bool:
    """Close the open state of ``kind`` about ``subject_key``. Returns whether one was open."""
    row = _open(session, kind, subject_key)
    if row is None:
        return False
    row.resolved_at = now or _now()
    return True


def resolve_others(
    session: Session, kind: Happening, still_open: set[str], *, now: datetime | None = None,
) -> int:
    """Close every open state of ``kind`` whose subject a check no longer found."""
    resolved = 0
    for row in session.scalars(select(AttentionState).where(
        AttentionState.kind == kind.value, AttentionState.resolved_at.is_(None),
    )):
        if row.subject_key not in still_open:
            row.resolved_at = now or _now()
            resolved += 1
    return resolved


def _may_see(session: Session, access: Access, row: AttentionState) -> bool:
    definition = DEFINITIONS[Happening(row.kind)]
    area, level = definition.audience
    if access.allows(area, level):
        return True
    # Anyone hears what needs them about the collections they added.
    if row.collection_id is None or access.user_id is None or definition.severity == Severity.PROBLEM:
        return False
    collection = session.get(Collection, row.collection_id)
    return collection is not None and collection.added_by_id == access.user_id and access.allows_source(collection.source_key)


def open_states(
    session: Session, access: Access, *, now: datetime | None = None,
) -> list[AttentionState]:
    """The open states this person may see and has not put off, problems first, the newest first within each."""
    now = now or _now()
    rows = session.scalars(select(AttentionState).where(
        AttentionState.resolved_at.is_(None),
        or_(AttentionState.put_off_until.is_(None), AttentionState.put_off_until <= now),
    ).order_by(AttentionState.opened_at.desc(), AttentionState.id.desc()))
    order = {severity: index for index, severity in enumerate(SEVERITY_ORDER)}
    visible = [row for row in rows if _may_see(session, access, row)]
    return sorted(visible, key=lambda row: order[DEFINITIONS[Happening(row.kind)].severity])
