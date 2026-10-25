"""VODLoft Sources.

A Source is everything VODLoft knows about one service. Each lives in its own
subpackage (``sources.dailywire``); the rest of VODLoft reaches it through the
contract in ``sources.contract`` and the registry below.
"""
from .contract import ANY_DOMAIN, EpisodeMedia, Feature, LinkKind, MoviePlayback, PlaybackKind, ProgramStatus, ResolvedLink, ShowDetails, Source, VideoDetails
from .registry import UnknownSourceError, all_sources, get_source, register, sources_for
from .dailywire import DailyWireSource
from .ytdlp import YtDlpSource

DAILYWIRE = "dailywire"

register(DailyWireSource())
# Claims every domain, so it comes after every Source that names its own.
register(YtDlpSource())

__all__ = [
    "ANY_DOMAIN",
    "DAILYWIRE",
    "DailyWireSource",
    "EpisodeMedia",
    "Feature",
    "LinkKind",
    "MoviePlayback",
    "PlaybackKind",
    "ProgramStatus",
    "ResolvedLink",
    "ShowDetails",
    "Source",
    "UnknownSourceError",
    "VideoDetails",
    "YtDlpSource",
    "all_sources",
    "get_source",
    "register",
    "sources_for",
]
