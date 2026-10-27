"""VODLoft Sources.

A Source is everything VODLoft knows about one service. Each lives in its own
subpackage (``sources.dailywire``); the rest of VODLoft reaches it through the
contract in ``sources.contract`` and the registry below.
"""
from .contract import ANY_DOMAIN, ApiKeyRejected, ApiQuotaShare, ApiStatus, EpisodeMedia, Feature, LinkKind, Playback, PlaybackKind, ProgramStatus, ResolvedLink, SeasonRef, ShowDetails, Source, SourceProblem, VideoDetails
from .registry import UnknownSourceError, all_sources, get_source, named_domains, register, sources_for
from .dailywire import DailyWireSource
from .npo import NpoSource
from .ytdlp import YtDlpSource

DAILYWIRE = DailyWireSource.id

register(DailyWireSource())
register(NpoSource())
# Claims every domain, so it comes after every Source that names its own.
register(YtDlpSource())

__all__ = [
    "ANY_DOMAIN",
    "ApiKeyRejected",
    "ApiQuotaShare",
    "ApiStatus",
    "DAILYWIRE",
    "DailyWireSource",
    "EpisodeMedia",
    "Feature",
    "LinkKind",
    "Playback",
    "NpoSource",
    "PlaybackKind",
    "ProgramStatus",
    "ResolvedLink",
    "SeasonRef",
    "ShowDetails",
    "Source",
    "SourceProblem",
    "UnknownSourceError",
    "VideoDetails",
    "YtDlpSource",
    "all_sources",
    "get_source",
    "register",
    "sources_for",
    "named_domains",
]
