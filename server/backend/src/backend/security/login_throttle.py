"""Slow down guessing passwords.

Failed sign-ins are counted per username and per address. After a few free
attempts each further failure doubles the wait before the next attempt is
heard, up to a few minutes. A successful sign-in clears the username's count.
The counts live in memory: a restart forgets them, which only ever helps the
person who forgot their password.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _Failures:
    count: int = 0
    blocked_until: float = 0.0


class LoginThrottle:
    def __init__(
        self,
        *,
        free_attempts_per_username: int = 5,
        free_attempts_per_address: int = 20,
        max_wait_seconds: float = 300.0,
        clock=time.monotonic,
    ) -> None:
        self._free = {"username": free_attempts_per_username, "address": free_attempts_per_address}
        self._max_wait = max_wait_seconds
        self._clock = clock
        self._failures: dict[tuple[str, str], _Failures] = {}
        self._lock = threading.Lock()

    def _keys(self, username: str, address: str | None) -> list[tuple[str, str]]:
        keys = [("username", username.strip().lower())]
        if address:
            keys.append(("address", address))
        return keys

    def wait_seconds(self, username: str, address: str | None) -> int:
        """Seconds until a sign-in for this username from this address is heard again; 0 when now."""
        now = self._clock()
        with self._lock:
            waits = [
                failures.blocked_until - now
                for key in self._keys(username, address)
                if (failures := self._failures.get(key)) is not None
            ]
        wait = max(waits, default=0.0)
        return int(wait) + 1 if wait > 0 else 0

    def record_failure(self, username: str, address: str | None) -> None:
        now = self._clock()
        with self._lock:
            for key in self._keys(username, address):
                failures = self._failures.setdefault(key, _Failures())
                failures.count += 1
                over = failures.count - self._free[key[0]]
                if over > 0:
                    failures.blocked_until = now + min(2.0 ** (over - 1), self._max_wait)

    def record_success(self, username: str) -> None:
        with self._lock:
            self._failures.pop(("username", username.strip().lower()), None)


login_throttle = LoginThrottle()
