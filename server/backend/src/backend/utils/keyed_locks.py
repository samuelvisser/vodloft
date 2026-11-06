from __future__ import annotations

import threading
from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)


class KeyedLocks(Generic[K]):
    """One lock per key, such as a file path or a download, so work on the same key takes turns.

    A key's lock exists while a thread holds it or waits for it, so locks for keys
    that are no longer used do not pile up.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[K, tuple[threading.Lock, list[int]]] = {}

    @contextmanager
    def hold(self, key: K, *, while_waiting: Callable[[], None] | None = None, poll_seconds: float = 0.1) -> Iterator[None]:
        """Hold the key's lock. ``while_waiting`` runs every ``poll_seconds`` until it is free,
        so a caller can stop waiting by raising, for example when its work was canceled."""
        with self._guard:
            lock, users = self._locks.setdefault(key, (threading.Lock(), [0]))
            users[0] += 1
        acquired = False
        try:
            if while_waiting is None:
                acquired = lock.acquire()
            else:
                while not (acquired := lock.acquire(timeout=poll_seconds)):
                    while_waiting()
            yield
        finally:
            if acquired:
                lock.release()
            with self._guard:
                users[0] -= 1
                if users[0] == 0:
                    del self._locks[key]
