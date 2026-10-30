"""The quick download history: one row per quick download, and how it ended.

Rows are written as a quick download moves along (started, ready, downloaded,
expired, discarded) and only while Settings › Quick download keeps a history.
A failure or cancel that happens inside the task system is filled in from the
operation when the history is read, so every path ends somewhere.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.db.core import get_session
from backend.db.models import QuickDownloadHistory
from config import get_settings

logger = logging.getLogger(__name__)

WORKING = "working"
READY = "ready"
DOWNLOADED = "downloaded"
EXPIRED = "expired"
DISCARDED = "discarded"
CANCELED = "canceled"
FAILED = "failed"
REFUSED = "refused"
FINISHED = frozenset({DOWNLOADED, EXPIRED, DISCARDED, CANCELED, FAILED, REFUSED})
INTERRUPTED_MESSAGE = "Stopped before it finished"


def history_enabled() -> bool:
    return get_settings().quick_download.keep_history


def _write(session: Session | None, work) -> None:
    """Run ``work`` in the caller's session, or in one of its own that commits."""
    if not history_enabled():
        return
    if session is not None:
        work(session)
        return
    own = get_session()
    try:
        work(own)
        own.commit()
    except Exception:
        own.rollback()
        logger.exception("Could not update the quick download history")
    finally:
        own.close()


def record_started(request, *, source_name: str, session: Session | None = None) -> None:
    """A quick download was asked for. ``request`` is a QuickDownloadRequest."""
    def work(s: Session) -> None:
        s.add(QuickDownloadHistory(
            quick_download_id=request.id, title=request.title, source_key=request.source_key,
            source_name=source_name, url=request.url, format=request.choice.label,
            choice=asdict(request.choice), outcome=WORKING,
        ))
    _write(session, work)


def record_refused(
    *, quick_id: str, title: str, source_key: str, source_name: str, url: str, choice, message: str,
    session: Session | None = None,
) -> None:
    """A link that VODLoft would not download, such as one protected by DRM."""
    def work(s: Session) -> None:
        now = datetime.now(timezone.utc)
        s.add(QuickDownloadHistory(
            quick_download_id=quick_id, title=title, source_key=source_key, source_name=source_name, url=url,
            format=choice.label, choice=asdict(choice), outcome=REFUSED, message=message,
            started_at=now, finished_at=now,
        ))
    _write(session, work)


def record_outcome(
    quick_id: str, outcome: str, *, size_bytes: int | None = None, message: str | None = None,
    only_from: Iterable[str] | None = None, session: Session | None = None,
) -> None:
    """Move one row on. With ``only_from``, rows in another state are left as they are."""
    def work(s: Session) -> None:
        row = s.scalar(select(QuickDownloadHistory).where(QuickDownloadHistory.quick_download_id == quick_id))
        if row is None or (only_from is not None and row.outcome not in set(only_from)):
            return
        row.outcome = outcome
        if size_bytes is not None:
            row.size_bytes = size_bytes
        if message is not None:
            row.message = message
        if outcome in FINISHED and row.finished_at is None:
            row.finished_at = datetime.now(timezone.utc)
    _write(session, work)


def reconcile_history(session: Session) -> None:
    """End rows still marked working whose quick download is no longer running."""
    from task_manager.scheduler.types import OperationStatus
    from task_manager.tasks.quick_download_operations import quick_download_operation

    working = session.scalars(select(QuickDownloadHistory).where(QuickDownloadHistory.outcome == WORKING)).all()
    for row in working:
        operation = quick_download_operation(session, row.quick_download_id)
        status = operation.status if operation is not None else None
        if status in (OperationStatus.QUEUED.value, OperationStatus.RUNNING.value, OperationStatus.WAITING.value):
            continue
        if status == OperationStatus.SUCCEEDED.value:
            # The worker records it as ready itself; only a row it could not update lands here.
            row.outcome = READY
            continue
        row.outcome = CANCELED if status == OperationStatus.CANCELED.value else FAILED
        row.message = (operation.message or operation.error) if operation is not None else INTERRUPTED_MESSAGE
        row.finished_at = (operation.finished_at if operation is not None else None) or datetime.now(timezone.utc)


def list_history(session: Session, *, limit: int = 500) -> list[QuickDownloadHistory]:
    reconcile_history(session)
    session.commit()
    return list(session.scalars(
        select(QuickDownloadHistory)
        .order_by(QuickDownloadHistory.started_at.desc(), QuickDownloadHistory.id.desc())
        .limit(limit)
    ))


def clear_history(session: Session) -> int:
    """Forget every finished quick download; ones still working or ready stay."""
    result = session.execute(delete(QuickDownloadHistory).where(QuickDownloadHistory.outcome.in_(FINISHED)))
    return result.rowcount or 0


def forget_old_history(*, now: datetime | None = None) -> int:
    """Forget entries older than the retention period. The sweep calls this."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=get_settings().quick_download.history_retention_days)
    session = get_session()
    try:
        result = session.execute(delete(QuickDownloadHistory).where(QuickDownloadHistory.started_at < cutoff))
        session.commit()
        return result.rowcount or 0
    finally:
        session.close()
