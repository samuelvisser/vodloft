from __future__ import annotations

import logging


def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:12345", "GET", path, "1.1", 200),
        exc_info=None,
    )


def test_logs_endpoint_access_is_not_captured():
    from backend.logging_buffer import is_logs_endpoint_access

    assert is_logs_endpoint_access(_access_record("/api/logs"))
    assert is_logs_endpoint_access(_access_record("/api/logs?limit=20000&level=INFO"))


def test_other_access_logs_are_still_captured():
    from backend.logging_buffer import is_logs_endpoint_access

    assert not is_logs_endpoint_access(_access_record("/api/pull"))
    assert not is_logs_endpoint_access(_access_record("/api/tasks/ledger?limit=100"))


def test_logs_endpoint_returns_newest_records_shortened_and_without_pull_requests(monkeypatch):
    from datetime import datetime, timezone

    from backend.api.endpoints.logs import router as logs_router
    from backend.logging_buffer import ApplicationLogEntry

    now = datetime.now(timezone.utc)
    entries = [
        ApplicationLogEntry(id=i, timestamp=now, level="INFO", logger="vodloft", message=f"record {i}")
        for i in range(1, 1501)
    ]
    entries.append(
        ApplicationLogEntry(
            id=1501, timestamp=now, level="INFO", logger="uvicorn.access",
            message='127.0.0.1:1 - "GET /api/pull?since=1 HTTP/1.1" 200',
        )
    )
    entries.append(ApplicationLogEntry(id=1502, timestamp=now, level="INFO", logger="vodloft", message="x" * 50_000))
    monkeypatch.setattr(logs_router, "get_application_logs", lambda: entries)

    page = logs_router.application_logs(
        level=None, search=None, hide_pull_requests=True, before=None, after=None, limit=1_000
    )

    assert page.total == 1501
    assert len(page.items) == 1_000
    assert page.items[0].id == 502
    assert all(item.logger != "uvicorn.access" for item in page.items)
    assert page.items[-1].message.startswith("x" * 10_000)
    assert page.items[-1].message.endswith("(40,000 more characters)")


def test_logs_endpoint_pages_before_and_after_a_record(monkeypatch):
    from datetime import datetime, timezone

    from backend.api.endpoints.logs import router as logs_router
    from backend.logging_buffer import ApplicationLogEntry

    now = datetime.now(timezone.utc)
    entries = [
        ApplicationLogEntry(id=i, timestamp=now, level="ERROR" if i % 2 else "INFO", logger="vodloft", message=str(i))
        for i in range(1, 101)
    ]
    monkeypatch.setattr(logs_router, "get_application_logs", lambda: entries)

    def page(**kwargs):
        options = {"level": None, "search": None, "hide_pull_requests": False, "before": None, "after": None}
        return logs_router.application_logs(**(options | kwargs))

    newest = page(limit=10)
    assert [item.id for item in newest.items] == list(range(91, 101))
    assert (newest.total, newest.has_older, newest.has_newer) == (100, True, False)

    older = page(before=91, limit=10)
    assert [item.id for item in older.items] == list(range(81, 91))
    assert older.has_older and older.has_newer

    first = page(before=6, limit=10)
    assert [item.id for item in first.items] == list(range(1, 6))
    assert not first.has_older

    newer = page(after=50, limit=10)
    assert [item.id for item in newer.items] == list(range(51, 61))
    assert newer.has_newer

    errors = page(level="error", after=94, limit=10)
    assert [item.id for item in errors.items] == [95, 97, 99]
    assert (errors.total, errors.has_older, errors.has_newer) == (50, True, False)
