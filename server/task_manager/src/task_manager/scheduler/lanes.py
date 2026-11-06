"""The worker pools tasks run in. A task picks its lane with ``@task(executor_alias=...)``."""
from __future__ import annotations

from enum import StrEnum


class TaskLane(StrEnum):
    DEFAULT = "default"
    """Most work, as many at a time as ``scheduler.max_workers`` allows."""
    DOWNLOADS = "downloads"
    """Downloads, as many at a time as the download settings allow."""
    BULK = "bulk"
    """One task of a bulk action per download, often thousands: one at a time, so
    they never crowd out other work or a cancel of that same bulk action."""
    METADATA = "metadata"
    """A metadata refresh queues one task per episode: a few at a time."""
    WATCHDOG = "watchdog"
    """The stalled-work watchdog, which must run while every other pool is full."""


BULK_WORKERS = 1
METADATA_WORKERS = 3
WATCHDOG_WORKERS = 1
