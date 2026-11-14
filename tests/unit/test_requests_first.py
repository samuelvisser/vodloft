"""Background tasks wait at their database queries while a page request is being answered."""
from __future__ import annotations

import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture
def requests_first(monkeypatch):
    from backend import requests_first

    monkeypatch.setattr(requests_first, "_answering", 0)
    monkeypatch.setattr(requests_first, "_no_requests", threading.Event())
    requests_first._no_requests.set()
    monkeypatch.setattr(requests_first, "_thread", threading.local())
    return requests_first


def _in_thread(work) -> float:
    """Seconds ``work`` took in a thread of its own, like a task worker."""
    took = []

    def run():
        started = time.monotonic()
        work()
        took.append(time.monotonic() - started)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(5)
    return took[0]


def _query(database):
    with database() as session:
        session.execute(text("SELECT 1"))


def test_a_background_query_waits_until_the_request_is_answered(requests_first, task_database, monkeypatch):
    monkeypatch.setattr(requests_first, "_LONGEST_WAIT", 5.0)
    requests_first.request_started()
    threading.Timer(0.3, requests_first.request_answered).start()

    def background():
        with requests_first.background_work():
            _query(task_database)

    assert 0.25 < _in_thread(background) < 2


def test_other_threads_never_wait(requests_first, task_database):
    """The request itself, and anything else that is not a background task, runs on."""
    requests_first.request_started()
    try:
        assert _in_thread(lambda: _query(task_database)) < 0.2
    finally:
        requests_first.request_answered()


def test_a_background_task_waits_a_short_while_at_most(requests_first, task_database, monkeypatch):
    """While the UI keeps asking, background work still goes on, and what a waiting task holds is soon free."""
    monkeypatch.setattr(requests_first, "_LONGEST_WAIT", 0.2)
    requests_first.request_started()
    try:
        def background():
            with requests_first.background_work():
                _query(task_database)

        assert 0.15 < _in_thread(background) < 1
    finally:
        requests_first.request_answered()


def test_a_background_task_never_waits_in_a_write_transaction(requests_first, task_database, monkeypatch):
    """Others may queue for its turn to write."""
    from backend.db.core import run_write_transaction

    monkeypatch.setattr(requests_first, "_LONGEST_WAIT", 5.0)

    def background():
        with requests_first.background_work():
            def work(session):
                requests_first.request_started()
                session.execute(text("SELECT 1"))

            run_write_transaction(work)

    try:
        assert _in_thread(background) < 1
    finally:
        requests_first.request_answered()


def test_a_request_counts_until_its_response_starts(requests_first):
    """A stream, such as a video, does not hold background work up while it plays."""
    seen = {}
    app = FastAPI()
    app.add_middleware(requests_first.RequestsFirstMiddleware)

    @app.get("/api/page")
    def page():
        seen["page"] = requests_first._answering
        return {}

    @app.get("/api/stream")
    def stream():
        def body():
            seen["streaming"] = requests_first._answering
            yield b"chunk"

        return StreamingResponse(body())

    with TestClient(app) as client:
        assert client.get("/api/page").status_code == 200
        assert client.get("/api/stream").content == b"chunk"

    assert seen == {"page": 1, "streaming": 0}
    assert requests_first._answering == 0
    assert requests_first._no_requests.is_set()


def test_a_background_task_can_wait_while_it_reads_a_large_result(requests_first, tmp_path, monkeypatch):
    """sqlite3 gives the GIL away at every row, so a long read is where requests wait most."""
    from sqlalchemy.engine import make_url

    from backend.db import core

    looks = []
    monkeypatch.setattr(core, "let_requests_go_first", lambda: looks.append(1))
    path = tmp_path / "rows.db"
    engine = core._create_sqlite_engine(make_url(f"sqlite:///{path}"), path)
    statement = text("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 100) SELECT i FROM n")
    try:
        with engine.connect() as connection:
            looks.clear()
            assert len(connection.execute(statement).all()) == 100
            outside = len(looks)
            with requests_first.background_work():
                assert len(connection.execute(statement).all()) == 100
            inside = len(looks) - outside
    finally:
        engine.dispose()

    # Every query looks once; a background read also looks between its rows.
    assert outside == 1
    assert inside > 10
