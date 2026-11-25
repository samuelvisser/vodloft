from __future__ import annotations

import re
from dataclasses import replace

from fastapi import APIRouter, Query

from backend.api.models.logs import ApplicationLogEntryRead, ApplicationLogPageRead
from backend.logging_buffer import ApplicationLogEntry, get_application_logs, max_application_log_entries
from backend.security.access import Area, Level
from backend.security.deps import requires


router = APIRouter(prefix="/logs", tags=["Logs"])

# The UI polls this endpoint every few seconds, so it only takes the newest records and cuts very long
# messages (a dumped API response, say).
_MAX_TEXT_LENGTH = 10_000
_PULL_REQUEST = re.compile(r'"\w+ /api/pull[?\s]')


def _is_pull_request(entry: ApplicationLogEntry) -> bool:
    return entry.logger == "uvicorn.access" and _PULL_REQUEST.search(entry.message) is not None


def _shortened(text: str | None) -> str | None:
    if text is None or len(text) <= _MAX_TEXT_LENGTH:
        return text
    cut = len(text) - _MAX_TEXT_LENGTH
    return f"{text[:_MAX_TEXT_LENGTH]}… ({cut:,} more characters)"


@router.get("", dependencies=[requires(Area.LOGS, Level.VIEW)], response_model=ApplicationLogPageRead)
def application_logs(
    level: str | None = None,
    search: str | None = None,
    hide_pull_requests: bool = Query(default=False, alias="hidePullRequests"),
    limit: int = Query(default=1_000, ge=1, le=5_000),
):
    """Return the newest retained application-wide log records in chronological order."""

    entries = get_application_logs()
    if level:
        requested_level = level.upper()
        entries = [entry for entry in entries if entry.level == requested_level]
    if hide_pull_requests:
        entries = [entry for entry in entries if not _is_pull_request(entry)]
    if search:
        needle = search.casefold()
        entries = [
            entry
            for entry in entries
            if needle in entry.logger.casefold()
            or needle in entry.message.casefold()
            or (entry.exception is not None and needle in entry.exception.casefold())
        ]

    total = len(entries)
    if len(entries) > limit:
        entries = entries[-limit:]

    return ApplicationLogPageRead(
        items=[
            ApplicationLogEntryRead.model_validate(
                replace(entry, message=_shortened(entry.message), exception=_shortened(entry.exception))
            )
            for entry in entries
        ],
        total=total,
        retained_limit=max_application_log_entries(),
    )
