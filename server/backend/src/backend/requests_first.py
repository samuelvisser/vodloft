"""Lets page requests go first: background tasks wait while someone waits for an answer.

API requests and background tasks are threads in one Python process, and Python runs one
of them at a time (the GIL), without priorities. A request gives the GIL away at every
database query and then waits behind every busy background thread to get it back, so a
page next to a busy sweep can take many times as long as on an idle server.

So while any request is being answered, a background task waits before its next database
query, and between the rows of a large result it reads, until no request is left. A request
counts until its response starts: a stream, such as a video or a feed, does not hold
background work up while it plays.

A task never waits in a write transaction, where others may queue for its turn to write, and
waits at most ``_LONGEST_WAIT`` at a time, then runs at least ``_RUNS_BETWEEN_WAITS`` before it
waits again. Background work therefore keeps going while the UI polls, and a request that
needs something a waiting task holds gets it soon.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_LONGEST_WAIT = 0.25
_RUNS_BETWEEN_WAITS = 0.01

_background: ContextVar[bool] = ContextVar("lets_requests_go_first", default=False)
_lock = threading.Lock()
_answering = 0
_no_requests = threading.Event()
_no_requests.set()
_thread = threading.local()


@contextmanager
def background_work() -> Iterator[None]:
    """Code in this block waits for page requests at its database queries."""
    token = _background.set(True)
    try:
        yield
    finally:
        _background.reset(token)


def in_background_work() -> bool:
    return _background.get()


def request_started() -> None:
    global _answering
    with _lock:
        _answering += 1
        _no_requests.clear()


def request_answered() -> None:
    global _answering
    with _lock:
        _answering -= 1
        if _answering == 0:
            _no_requests.set()


def let_requests_go_first() -> None:
    """In background work, wait while a request is being answered."""
    if _no_requests.is_set() or not _background.get():
        return
    now = time.monotonic()
    if now - getattr(_thread, "resumed", 0.0) < _RUNS_BETWEEN_WAITS:
        return
    _no_requests.wait(_LONGEST_WAIT)
    _thread.resumed = time.monotonic()


class RequestsFirstMiddleware:
    """Counts the requests VODLoft is answering, from when one comes in until its response starts."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_started()
        answered = False

        def done() -> None:
            nonlocal answered
            if not answered:
                answered = True
                request_answered()

        async def send_and_count(message) -> None:
            if message["type"] == "http.response.start":
                done()
            await send(message)

        try:
            await self.app(scope, receive, send_and_count)
        finally:
            done()
