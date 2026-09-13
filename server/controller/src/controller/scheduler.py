from __future__ import annotations

from task_manager import get_runtime, start_task_system, stop_task_system


def start_scheduler():
    """Compatibility wrapper retained for callers from the original foundation."""
    return start_task_system()


def stop_scheduler() -> None:
    stop_task_system()


def reload_scheduler() -> None:
    runtime = get_runtime()
    if runtime.started:
        runtime.reload_schedules()
