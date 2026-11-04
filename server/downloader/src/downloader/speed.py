"""One speed limit shared by every download that runs at the same time.

The application says what the limit is right now through ``configure``; the downloader only enforces it. A
change applies to the next chunk of a running download. A pause holds downloads that have not started yet.

The downloader also measures how fast transfers run when nothing slows them down, so the application can estimate
the connection's speed (``fastest_recent``).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterator

from .errors import DownloadCanceled

_MIN_SAMPLE_BYTES = 5 * 1024 * 1024
_WINDOW_SECONDS = 10.0
_IDLE_SECONDS = 2.0
_SAMPLES = 20


@dataclass(frozen=True)
class SpeedPolicy:
    bytes_per_second: float | None = None
    """None means full speed."""
    paused_until: float | None = None
    """A ``time.time()`` until which downloads wait, or None."""


class SpeedLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._policy: Callable[[], SpeedPolicy] = SpeedPolicy
        self._next_free = 0.0
        self._samples: deque[float] = deque(maxlen=_SAMPLES)
        self._on_sample: Callable[[float], None] | None = None
        # A measuring window over every download together: the connection's speed, not one file's.
        self._window_start = 0.0
        self._window_last = 0.0
        self._window_bytes = 0
        self._window_slowed = False

    def configure(self, policy: Callable[[], SpeedPolicy], *, samples: list[float] | None = None,
                  on_sample: Callable[[float], None] | None = None) -> None:
        """``policy`` is asked before every chunk; ``samples`` are earlier measurements, ``on_sample`` stores new ones."""
        with self._lock:
            self._policy = policy
            self._samples = deque(samples or [], maxlen=_SAMPLES)
            self._on_sample = on_sample

    def policy(self) -> SpeedPolicy:
        try:
            return self._policy()
        except Exception:  # A broken policy must never stop downloads.
            return SpeedPolicy()

    def wait_while_paused(self, should_cancel: Callable[[], bool] | None = None,
                          waiting: Callable[[float | None], None] | None = None) -> None:
        """Hold a download while downloads are paused, for example at night."""
        announced = False
        while True:
            paused_until = self.policy().paused_until
            if paused_until is None or paused_until <= time.time():
                if announced and waiting:
                    waiting(None)
                return
            if should_cancel and should_cancel():
                raise DownloadCanceled("Canceled while downloads were paused")
            if not announced and waiting:
                waiting(paused_until)
                announced = True
            time.sleep(min(1.0, max(0.05, paused_until - time.time())))

    def _measure(self, size: int, slowed: bool) -> None:
        sample = None
        with self._lock:
            now = time.monotonic()
            if now - self._window_last > _IDLE_SECONDS:
                self._window_start, self._window_bytes, self._window_slowed = now, 0, False
            self._window_last = now
            self._window_bytes += size
            self._window_slowed = self._window_slowed or slowed
            elapsed = now - self._window_start
            if elapsed >= _WINDOW_SECONDS:
                if not self._window_slowed and self._window_bytes >= _MIN_SAMPLE_BYTES:
                    sample = self._window_bytes / elapsed
                self._window_start, self._window_bytes, self._window_slowed = now, 0, False
        if sample is not None:
            self.record(sample)

    def throttle(self, size: int, should_cancel: Callable[[], bool] | None = None) -> bool:
        """Account for ``size`` bytes; sleeps when the shared limit is used up. True when it had to wait."""
        slowed = self._wait(size, should_cancel)
        self._measure(size, slowed)
        return slowed

    def _wait(self, size: int, should_cancel: Callable[[], bool] | None) -> bool:
        # A pause only holds downloads that have not started: a connection left idle for hours would break.
        limit = self.policy().bytes_per_second
        if not limit or limit <= 0:
            return False
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_free)
            self._next_free = start + size / limit
            delay = start - now
        if delay <= 0:
            return False
        end = time.monotonic() + delay
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return True
            if should_cancel and should_cancel():
                raise DownloadCanceled("Download canceled")
            time.sleep(min(0.25, left))

    def record(self, bytes_per_second: float) -> None:
        with self._lock:
            self._samples.append(bytes_per_second)
            on_sample = self._on_sample
        if on_sample:
            try:
                on_sample(bytes_per_second)
            except Exception:
                pass

    def fastest_recent(self, minimum_samples: int = 3) -> float | None:
        """The fastest recent unthrottled transfer, once there are a few."""
        with self._lock:
            samples = list(self._samples)
        return max(samples) if len(samples) >= minimum_samples else None

    def share(self, active: int) -> float | None:
        """One download's part of the limit, for a program such as yt-dlp that takes a fixed rate."""
        limit = self.policy().bytes_per_second
        return limit / max(1, active) if limit else None


limiter = SpeedLimiter()
