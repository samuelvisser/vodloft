"""Locks on lock files, so workers in separate processes take turns on the same work.

portalocker uses flock on POSIX and byte-range locks on Windows; shared locks on
Windows need its win32 extra. Both lock per open file handle, so two holders in the
same process exclude each other just as separate worker processes do. Lock files
stay where they are: another process can still have one open.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import BinaryIO

import portalocker

from config import get_settings


def lock_file_path(kind: str, name: str) -> Path:
    """The lock file ``name`` among the ``kind`` locks in the configured lock folder."""
    directory = Path(get_settings().download_settings.lock_root) / kind
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{name}.lock"


def _try_lock(lock_file: BinaryIO, shared: bool) -> bool:
    try:
        portalocker.lock(lock_file, (portalocker.LOCK_SH if shared else portalocker.LOCK_EX) | portalocker.LOCK_NB)
    except portalocker.AlreadyLocked:
        return False
    return True


@contextmanager
def file_lock(
    path: Path, *, shared: bool = False, timeout_seconds: float | None = None, poll_seconds: float = 0.05,
    holder: str = "another worker",
) -> Iterator[None]:
    """Hold the lock on ``path``. Raises TimeoutError, naming the ``holder`` it waited for,
    when the lock stays taken longer than ``timeout_seconds``."""
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    with path.open("a+b") as lock_file:
        while not _try_lock(lock_file, shared):
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for {holder}")
            time.sleep(poll_seconds)
        try:
            yield
        finally:
            portalocker.unlock(lock_file)


@asynccontextmanager
async def async_file_lock(path: Path, *, shared: bool = False, poll_seconds: float = 0.25) -> AsyncIterator[None]:
    """``file_lock`` for async work: waiting gives way to other tasks."""
    with path.open("a+b") as lock_file:
        while not _try_lock(lock_file, shared):
            await asyncio.sleep(poll_seconds)
        try:
            yield
        finally:
            portalocker.unlock(lock_file)
