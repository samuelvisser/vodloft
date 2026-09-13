from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

Worker = Callable[[Any, str, int, dict[str, Any]], Any]
TerminalCallback = Callable[[int, str], None]


@dataclass(slots=True)
class TriggerMeta:
    trigger_type: str
    cron: str | None = None
    interval_minutes: int | None = None
    event_name: str | None = None
    resource_type: str | None = None
    resource_id: int | None = None
    coalesce: bool = True


@dataclass(slots=True)
class TaskMeta:
    key: str
    title: str
    description: str = ""
    allowed_resource_types: tuple[str, ...] = ("system", "collection", "video")
    default_max_retries: int | None = None
    tracks_progress: bool = True
    terminal_callback: TerminalCallback | None = None
    max_concurrency: int | None = None
    triggers: list[TriggerMeta] = field(default_factory=list)


_REGISTRY: dict[str, tuple[TaskMeta, Worker]] = {}


def task(
    key: str,
    title: str,
    description: str = "",
    allowed_resource_types: tuple[str, ...] | None = None,
    default_max_retries: int | None = None,
    tracks_progress: bool = True,
    terminal_callback: TerminalCallback | None = None,
    max_concurrency: int | None = None,
):
    if max_concurrency is not None and max_concurrency < 1:
        raise ValueError("max_concurrency must be at least one")

    def decorator(fn: Worker) -> Worker:
        meta = TaskMeta(
            key=key,
            title=title,
            description=description,
            allowed_resource_types=allowed_resource_types or ("system", "collection", "video"),
            default_max_retries=default_max_retries,
            tracks_progress=tracks_progress,
            terminal_callback=terminal_callback,
            max_concurrency=max_concurrency,
            triggers=list(getattr(fn, "_pending_task_triggers", [])),
        )
        _REGISTRY[key] = (meta, fn)
        setattr(fn, "_task_meta", meta)
        return fn
    return decorator


def _attach_trigger(fn: Worker, trigger: TriggerMeta) -> Worker:
    meta = getattr(fn, "_task_meta", None)
    if meta is not None:
        meta.triggers.append(trigger)
    else:
        pending = list(getattr(fn, "_pending_task_triggers", []))
        pending.append(trigger)
        setattr(fn, "_pending_task_triggers", pending)
    return fn


def on_cron(
    cron: str,
    resource_type: str = "system",
    resource_id: int = 0,
    coalesce: bool = True,
):
    def decorator(fn: Worker) -> Worker:
        return _attach_trigger(
            fn,
            TriggerMeta(
                trigger_type="cron",
                cron=cron,
                resource_type=resource_type,
                resource_id=resource_id,
                coalesce=coalesce,
            ),
        )
    return decorator


def on_interval(
    minutes: int,
    resource_type: str = "system",
    resource_id: int = 0,
    coalesce: bool = True,
):
    if minutes < 1:
        raise ValueError("Interval must be at least one minute")

    def decorator(fn: Worker) -> Worker:
        return _attach_trigger(
            fn,
            TriggerMeta(
                trigger_type="interval",
                interval_minutes=minutes,
                resource_type=resource_type,
                resource_id=resource_id,
                coalesce=coalesce,
            ),
        )
    return decorator


def on_event(event_name: str, resource_type: str | None = None):
    def decorator(fn: Worker) -> Worker:
        return _attach_trigger(
            fn,
            TriggerMeta(
                trigger_type="event",
                event_name=event_name,
                resource_type=resource_type,
            ),
        )
    return decorator


def get_task(key: str) -> tuple[TaskMeta, Worker]:
    return _REGISTRY[key]


def all_tasks() -> dict[str, tuple[TaskMeta, Worker]]:
    return dict(_REGISTRY)


def all_definitions() -> list[TaskMeta]:
    return [meta for meta, _ in _REGISTRY.values()]


def all_triggers() -> dict[str, list[TriggerMeta]]:
    return {key: list(meta.triggers) for key, (meta, _) in _REGISTRY.items() if meta.triggers}
