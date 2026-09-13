from __future__ import annotations

_loaded = False


def load_all_tasks() -> None:
    global _loaded
    if _loaded:
        return
    from .workers import downloads, maintenance, synchronization  # noqa: F401
    _loaded = True
