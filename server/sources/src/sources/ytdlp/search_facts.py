"""The short facts a search result shows, such as "18.1M subscribers" or "19:05", alike on every Site."""
from __future__ import annotations

from datetime import datetime


def count(value) -> str | None:
    """18100000 as 18.1M, 2400 as 2.4K."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if number >= size:
            return f"{number / size:.1f}".removesuffix(".0") + suffix
    return str(number)


def plural(value, word: str) -> str | None:
    shown = count(value)
    if shown is None:
        return None
    return f"{shown} {word}" if shown == "1" else f"{shown} {word}s"


def length(seconds: float | None) -> str | None:
    if not seconds:
        return None
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def date(value: datetime | None) -> str | None:
    return f"{value.day} {value:%b %Y}" if value else None


def facts(*found: str | None) -> tuple[str, ...]:
    return tuple(fact for fact in found if fact)
