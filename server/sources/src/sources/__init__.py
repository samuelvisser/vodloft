"""VODLoft Sources.

A Source is everything VODLoft knows about one service. Each lives in its own
subpackage (``sources.dailywire``); the rest of VODLoft reaches it through the
contract in ``sources.contract`` and the registry below.
"""
from .contract import ANY_DOMAIN, EpisodeMedia, Feature, LinkKind, MoviePlayback, ResolvedLink, Source, VideoDetails
from .registry import UnknownSourceError, all_sources, get_source, register, sources_for
from .dailywire import DailyWireSource

DAILYWIRE = "dailywire"

register(DailyWireSource())

__all__ = [
    "ANY_DOMAIN",
    "DAILYWIRE",
    "DailyWireSource",
    "EpisodeMedia",
    "Feature",
    "LinkKind",
    "MoviePlayback",
    "ResolvedLink",
    "Source",
    "UnknownSourceError",
    "VideoDetails",
    "all_sources",
    "get_source",
    "register",
    "sources_for",
]
