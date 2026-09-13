from __future__ import annotations

from collections.abc import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger


class TaskScheduler:
    """Small provider-neutral wrapper around APScheduler.

    Application packages register callable jobs; this package deliberately has
    no knowledge of videos, collections, yt-dlp or database models.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()

    @property
    def running(self) -> bool:
        return self._scheduler.running

    def add_interval_job(
        self,
        job_id: str,
        function: Callable[[], None],
        *,
        minutes: int,
    ) -> None:
        self._scheduler.add_job(
            function,
            trigger=IntervalTrigger(minutes=minutes),
            id=job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
