"""Which Sources VODLoft follows upcoming and live episodes of, and how."""
from __future__ import annotations

from sources import Feature, Source, UnknownSourceError, get_source


def checks_pending(source: Source) -> bool:
    """The Source looks a batch of upcoming and live episodes up at once, through ``Source.check_pending``."""
    return source.has(Feature.PENDING_CHECKS)


def monitors_pending(source: Source) -> bool:
    """VODLoft looks the Source's upcoming and live episodes up one by one, as for The Daily Wire."""
    return source.has(Feature.LIVE_EPISODES) and source.has(Feature.EPISODE_LOOKUPS)


def follows_pending(source_key: str) -> bool:
    try:
        source = get_source(source_key)
    except UnknownSourceError:
        return False
    return checks_pending(source) or monitors_pending(source)
