from __future__ import annotations

import logging
import re
from bisect import bisect_left, bisect_right
from dataclasses import replace
from typing import Literal

from config import get_settings
from fastapi import APIRouter, Query

from backend.api.models.logs import ApplicationLogEntryRead, ApplicationLogPageRead
from backend.logging_buffer import ApplicationLogEntry, get_application_logs, max_application_log_entries
from backend.security.access import Area, Level
from backend.security.deps import requires


router = APIRouter(prefix="/logs", tags=["Logs"])

# The UI reads the log a page at a time: the newest records first, older ones while the user scrolls up,
# and new ones as they come in. It cuts very long messages (a dumped API response, say).
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
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = Query(
        default=None, description="Show this level and every more severe one. Defaults to the configured log level."
    ),
    search: str | None = None,
    hide_pull_requests: bool = Query(default=False, alias="hidePullRequests"),
    before: int | None = Query(default=None, description="Only records older than this record id."),
    after: int | None = Query(default=None, description="Only records newer than this record id."),
    limit: int = Query(default=1_000, ge=1, le=5_000),
):
    """Return one page of retained application-wide log records in chronological order.

    Without ``before`` or ``after`` it is the newest page. ``before`` gives the page just before that record and
    ``after`` the page just after it, so following ``hasNewer`` never skips a record."""

    entries = get_application_logs()
    level = level or get_settings().log_level
    level_numbers = logging.getLevelNamesMapping()
    threshold = level_numbers[level]
    # A record with a level name logging does not know counts as the lowest level.
    entries = [entry for entry in entries if level_numbers.get(entry.level, 0) >= threshold]
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
    ids = [entry.id for entry in entries]
    if after is not None:
        start = bisect_right(ids, after)
        end = min(start + limit, total)
    else:
        end = bisect_left(ids, before) if before is not None else total
        start = max(0, end - limit)

    return ApplicationLogPageRead(
        items=[
            ApplicationLogEntryRead.model_validate(
                replace(entry, message=_shortened(entry.message), exception=_shortened(entry.exception))
            )
            for entry in entries[start:end]
        ],
        total=total,
        level=level,
        has_older=start > 0,
        has_newer=end < total,
        retained_limit=max_application_log_entries(),
    )
