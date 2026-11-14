"""Says what the rest of VODLoft was doing while a request was slow.

API requests and task threads share one Python process. A request that is slow on a
busy server is usually waiting for those threads, not for its own query, so its own
timings do not explain it. While a request waits longer than a second, this samples
where every other thread is and logs the ones that are working: every second at first,
then less and less often, so a request that waits a minute still shows what held it up.
All of it is logged at DEBUG, so it shows only when the log level is DEBUG.
"""

from __future__ import annotations

import itertools
import logging
import sys
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SLOW_REQUEST_SECONDS = 1.0
_SAMPLE_EVERY_SECONDS = 1.0
_SAMPLES_PER_REQUEST = 10
_STEADY_SAMPLES = 3
"""Samples a second apart; each one after them waits twice as long as the one before."""
_THREADS_PER_SAMPLE = 12
_FRAMES_PER_THREAD = 4

# A thread with none of VODLoft's own code on its stack is a pool worker waiting for work.
_OWN_CODE = ("/backend/", "/task_manager/", "/sources/", "/downloader/", "/importer/", "/controller/")


@dataclass
class _Request:
    method: str
    path: str
    started: float
    samples: int = 0


_requests: dict[int, _Request] = {}
_request_ids = itertools.count(1)
_lock = threading.Lock()
_watcher: threading.Thread | None = None


def _logging() -> bool:
    """Whether the log level is DEBUG. These diagnostics are too much for an ordinary log."""
    return logger.isEnabledFor(logging.DEBUG)


def _say(message: str) -> None:
    """Into VODLoft's own log and the server's output, where `docker logs` shows it."""
    logger.debug(message)
    print(message, file=sys.stderr, flush=True)


def _place(frame) -> str:
    filename = frame.f_code.co_filename
    for marker in ("/src/", "/site-packages/", "/lib/"):
        if marker in filename:
            filename = filename.rsplit(marker, 1)[-1]
            break
    return f"{filename}:{frame.f_lineno} {frame.f_code.co_name}"


def _is_own(frame) -> bool:
    filename = frame.f_code.co_filename
    return __file__ != filename and "/site-packages/" not in filename and any(part in filename for part in _OWN_CODE)


def working_threads(*, skip: frozenset[int] = frozenset()) -> list[str]:
    """One line for every thread that runs VODLoft's code: where it stands, and from where in VODLoft.

    A thread that waits for the database, the network or its turn to write is listed too:
    what a slow request waits behind is often waiting itself.
    """
    names = {thread.ident: thread.name for thread in threading.enumerate()}
    lines = []
    for thread_id, innermost in sys._current_frames().items():
        if thread_id in skip:
            continue
        own = []
        frame = innermost
        while frame is not None:
            if _is_own(frame):
                own.append(frame)
            frame = frame.f_back
        if not own:
            continue
        places = [_place(innermost)] if innermost is not own[0] else []
        places += [_place(frame) for frame in own[:_FRAMES_PER_THREAD]]
        lines.append(f"{names.get(thread_id, thread_id)}: {' < '.join(places)}")
    return lines


def _sample_at(samples: int) -> float:
    """How long a request has waited when it is sampled again, after this many samples."""
    if samples < _STEADY_SAMPLES:
        return SLOW_REQUEST_SECONDS + samples * _SAMPLE_EVERY_SECONDS
    last_steady = SLOW_REQUEST_SECONDS + (_STEADY_SAMPLES - 1) * _SAMPLE_EVERY_SECONDS
    return last_steady * 2 ** (samples - _STEADY_SAMPLES + 1)


def _watch() -> None:
    while True:
        time.sleep(_SAMPLE_EVERY_SECONDS / 4)
        now = time.monotonic()
        with _lock:
            due = [
                request for request in _requests.values()
                if request.samples < _SAMPLES_PER_REQUEST
                and now - request.started >= _sample_at(request.samples)
            ]
            for request in due:
                request.samples += 1
        if not due or not _logging():
            continue
        lines = working_threads(skip=frozenset({threading.get_ident()}))
        waiting = ", ".join(f"{request.method} {request.path} ({now - request.started:.1f}s)" for request in due)
        shown = "\n  ".join(lines[:_THREADS_PER_SAMPLE]) or "no thread is working"
        more = f"\n  and {len(lines) - _THREADS_PER_SAMPLE} more" if len(lines) > _THREADS_PER_SAMPLE else ""
        _say(f"Still waiting for {waiting}. Working threads:\n  {shown}{more}")


def _ensure_watcher() -> None:
    global _watcher
    if _watcher is not None and _watcher.is_alive():
        return
    with _lock:
        if _watcher is None or not _watcher.is_alive():
            _watcher = threading.Thread(target=_watch, name="slow-request-watcher", daemon=True)
            _watcher.start()


class SlowRequestMiddleware:
    """Times every API request until its answer starts, and logs the slow ones."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return

        _ensure_watcher()
        request_id = next(_request_ids)
        request = _Request(method=scope["method"], path=scope["path"], started=time.monotonic())
        with _lock:
            _requests[request_id] = request

        def finish() -> None:
            with _lock:
                if _requests.pop(request_id, None) is None:
                    return
            took = time.monotonic() - request.started
            if took >= SLOW_REQUEST_SECONDS and _logging():
                _say(f"Slow request: {request.method} {request.path} answered after {took:.1f}s")

        async def send_and_time(message) -> None:
            # A stream or a long download is not slow for as long as it sends.
            if message["type"] == "http.response.start":
                finish()
            await send(message)

        try:
            await self.app(scope, receive, send_and_time)
        finally:
            finish()
