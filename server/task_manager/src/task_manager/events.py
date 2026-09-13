from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import RLock
from typing import Any


@dataclass(slots=True, frozen=True)
class Event:
    name: str
    resource_type: str
    resource_id: int
    payload: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[[Event], None]]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, event_name: str, callback: Callable[[Event], None]) -> None:
        with self._lock:
            self._listeners[event_name].append(callback)

    def clear(self) -> None:
        with self._lock:
            self._listeners.clear()

    def emit(self, event: Event) -> None:
        with self._lock:
            listeners = tuple(self._listeners.get(event.name, ()))
        for callback in listeners:
            callback(event)


EVENT_BUS = EventBus()
