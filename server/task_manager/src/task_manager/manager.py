from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from threading import Event, RLock
from typing import Any, Callable
from uuid import uuid4


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    id: str
    name: str
    status: TaskStatus
    progress: int
    message: str | None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result: Any = None


class TaskContext:
    def __init__(self, task_id: str, manager: "TaskManager", cancel_event: Event):
        self.task_id = task_id
        self._manager = manager
        self._cancel_event = cancel_event

    def report(self, progress: int, message: str | None = None) -> None:
        self.check_cancelled()
        self._manager._update(
            self.task_id,
            progress=max(0, min(100, int(progress))),
            message=message,
        )

    def check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise TaskCancelled("Task cancellation requested")


class TaskManager:
    def __init__(self, max_workers: int = 3):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="vodloft")
        self._lock = RLock()
        self._tasks: dict[str, TaskSnapshot] = {}
        self._cancel_events: dict[str, Event] = {}

    def submit(self, name: str, target: Callable[[TaskContext], Any]) -> TaskSnapshot:
        task_id = str(uuid4())
        now = datetime.now(timezone.utc)
        snapshot = TaskSnapshot(task_id, name, TaskStatus.QUEUED, 0, None, now)
        cancel_event = Event()
        with self._lock:
            self._tasks[task_id] = snapshot
            self._cancel_events[task_id] = cancel_event
        self._executor.submit(self._run, task_id, target, cancel_event)
        return snapshot

    def _run(self, task_id: str, target: Callable[[TaskContext], Any], cancel_event: Event) -> None:
        self._update(task_id, status=TaskStatus.RUNNING, started_at=datetime.now(timezone.utc))
        context = TaskContext(task_id, self, cancel_event)
        try:
            context.check_cancelled()
            result = target(context)
            context.check_cancelled()
        except TaskCancelled:
            self._update(
                task_id,
                status=TaskStatus.CANCELLED,
                finished_at=datetime.now(timezone.utc),
                message="Cancelled",
            )
        except Exception as exc:
            self._update(
                task_id,
                status=TaskStatus.FAILED,
                finished_at=datetime.now(timezone.utc),
                error=str(exc),
                message="Failed",
            )
        else:
            self._update(
                task_id,
                status=TaskStatus.SUCCEEDED,
                progress=100,
                finished_at=datetime.now(timezone.utc),
                result=result,
                message="Completed",
            )

    def _update(self, task_id: str, **changes: Any) -> None:
        with self._lock:
            current = self._tasks[task_id]
            self._tasks[task_id] = replace(current, **changes)

    def get(self, task_id: str) -> TaskSnapshot | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list(self) -> list[TaskSnapshot]:
        with self._lock:
            return sorted(self._tasks.values(), key=lambda item: item.created_at, reverse=True)

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(task_id)
            snapshot = self._tasks.get(task_id)
            if event is None or snapshot is None or snapshot.status in {
                TaskStatus.SUCCEEDED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }:
                return False
            event.set()
            self._tasks[task_id] = replace(snapshot, message="Cancellation requested")
            return True
