"""Which Sources exist, and which Source handles a link."""
from __future__ import annotations

from .contract import Source


class UnknownSourceError(LookupError):
    pass


_sources: dict[str, Source] = {}


def register(source: Source) -> Source:
    if source.id in _sources:
        raise ValueError(f"Source '{source.id}' is already registered")
    _sources[source.id] = source
    return source


def get_source(source_id: str) -> Source:
    try:
        return _sources[source_id]
    except KeyError:
        raise UnknownSourceError(f"No Source is registered as '{source_id}'") from None


def all_sources() -> list[Source]:
    return list(_sources.values())


def sources_for(url: str) -> list[Source]:
    """All Sources that claim the link's domain, in registration order."""
    return [source for source in _sources.values() if source.handles(url)]
