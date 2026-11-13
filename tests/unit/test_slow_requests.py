from __future__ import annotations

import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_a_slow_request_logs_the_threads_that_were_working(monkeypatch, capsys):
    """A request that is slow on a busy server waits for task threads, so the log has to say
    what those were doing: the request's own timings do not explain it."""
    from backend import slow_requests

    monkeypatch.setattr(slow_requests, "SLOW_REQUEST_SECONDS", 0.2)
    monkeypatch.setattr(slow_requests, "_SAMPLE_EVERY_SECONDS", 0.2)

    app = FastAPI()
    app.add_middleware(slow_requests.SlowRequestMiddleware)

    @app.get("/api/slow")
    def slow():
        time.sleep(0.6)
        return {}

    @app.get("/api/fast")
    def fast():
        return {}

    with TestClient(app) as client:
        assert client.get("/api/fast").status_code == 200
        assert client.get("/api/slow").status_code == 200

    logged = capsys.readouterr().err
    assert "Slow request: GET /api/slow answered after" in logged
    assert "Still waiting for GET /api/slow" in logged
    assert "/api/slow" in logged
    assert "/api/fast" not in logged


def test_a_request_that_waits_long_is_still_sampled_after_the_first_seconds(monkeypatch, capsys):
    """What holds a request up for a minute is often not what held it up in its first seconds."""
    from backend import slow_requests

    monkeypatch.setattr(slow_requests, "SLOW_REQUEST_SECONDS", 0.1)
    monkeypatch.setattr(slow_requests, "_SAMPLE_EVERY_SECONDS", 0.1)

    app = FastAPI()
    app.add_middleware(slow_requests.SlowRequestMiddleware)

    @app.get("/api/long")
    def long():
        time.sleep(0.9)
        return {}

    with TestClient(app) as client:
        assert client.get("/api/long").status_code == 200

    # A sample a second apart at first (here a tenth), then one after twice as long.
    assert capsys.readouterr().err.count("Still waiting for GET /api/long") == 4


def test_pool_workers_waiting_for_work_are_left_out_of_the_working_threads():
    from backend.slow_requests import working_threads

    released = threading.Event()
    waiter = threading.Thread(target=released.wait, name="waiting-task", daemon=True)
    waiter.start()
    try:
        assert not [line for line in working_threads() if line.startswith("waiting-task")]
    finally:
        released.set()
        waiter.join()


def test_a_thread_waiting_for_its_turn_to_write_is_listed_with_where_it_waits():
    from backend.db import core
    from backend.slow_requests import working_threads

    turns = core._WriteTurns()
    assert turns.take("background", 1)
    waiter = threading.Thread(target=turns.take, args=("background", 5), name="queued-writer", daemon=True)
    waiter.start()
    try:
        time.sleep(0.2)
        [line] = [line for line in working_threads() if line.startswith("queued-writer")]
        assert "backend/db/core.py" in line and " take" in line
    finally:
        turns.give_back()
        waiter.join()
