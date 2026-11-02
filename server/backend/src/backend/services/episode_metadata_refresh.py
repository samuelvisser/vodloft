"""Which episodes the per-episode metadata refresh may look up at their Source.

The metadata refresh follows an episode for a while after it is published and
reads it again from The Daily Wire. A Source that lists its episodes
(``Feature.EPISODE_LISTS``) keeps them up to date with the daily catalogue
refresh instead, and the per-episode refresh must never touch them: The Daily
Wire does not know them, and its "not found" would mark them as having no
usable media.
"""
from __future__ import annotations

from sources import Feature, UnknownSourceError, all_sources, get_source


def refreshes_episode_metadata(source_key: str) -> bool:
    try:
        source = get_source(source_key)
    except UnknownSourceError:
        return False
    return not source.has(Feature.EPISODE_LISTS)


def episode_metadata_refresh_source_keys() -> list[str]:
    return [source.id for source in all_sources() if not source.has(Feature.EPISODE_LISTS)]
