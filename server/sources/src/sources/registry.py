"""Which Sources exist, and which Source handles a link."""
from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from .contract import ANY_DOMAIN, Source


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


def _on_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def sources_for(url: str, preferred: Mapping[str, str] | None = None) -> list[Source]:
    """All Sources that claim the link's domain, in registration order.

    Sources that claim every domain (``*``) come after the ones that name it.
    ``preferred`` maps a domain to the Source the user prefers for it; that
    Source comes first for links on the domain or a subdomain of it.
    """
    matching = sorted(
        (source for source in _sources.values() if source.handles(url)),
        key=lambda source: ANY_DOMAIN in source.domains,
    )
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    # The most specific domain wins, so a subdomain can prefer another Source.
    for domain, source_id in sorted((preferred or {}).items(), key=lambda item: -len(item[0])):
        if _on_domain(host, domain):
            matching.sort(key=lambda source: source.id != source_id)
            break
    return matching


def named_domains() -> list[str]:
    """Every domain a Source names, so the user can pick a preferred Source per domain."""
    return sorted({domain for source in _sources.values() for domain in source.domains if domain != ANY_DOMAIN})
