"""VODLoft Sources.

A Source is everything VODLoft knows about one service. Each lives in its own
subpackage (``sources.dailywire``); the rest of VODLoft reaches it through the
contract in ``sources.contract`` and the registry below.
"""
from .contract import ANY_DOMAIN, ApiKeyRejected, ApiQuotaShare, ApiStatus, EpisodeMedia, EpisodePublishStatus, EpisodeTag, PublishStatusLabel, Feature, ItemRef, ItemRefresh, MAIN_TAG, MIN_NEWEST_EPISODES, LinkKind, LinkPreview, MediaStream, Playback, PlaybackKind, ProgramStatus, ResolvedLink, RssEpisodeType, SearchNotice, SearchResults, SeasonRef, CollectionDetails, CookiesStatus, Site, Source, SourceProblem, SponsorBlockSegment, StreamMethod, UpgradeOffer, VideoDetails, VideoFormat, VideoFormats
from .registry import UnknownSourceError, all_sources, collection_on_site, get_source, named_site_for, named_sites, register, site_for, sources_for
from .dailywire import DailyWireSource
from .npo import NpoSource
from .ytdlp import YtDlpSource

DAILYWIRE = DailyWireSource.id

register(DailyWireSource())
register(NpoSource())
# Claims every domain, so it comes after every Source that names its own.
register(YtDlpSource())

__all__ = [
    "LinkPreview",
    "ANY_DOMAIN",
    "ApiKeyRejected",
    "ApiQuotaShare",
    "ApiStatus",
    "DAILYWIRE",
    "DailyWireSource",
    "EpisodeMedia",
    "EpisodePublishStatus",
    "EpisodeTag",
    "PublishStatusLabel",
    "Feature",
    "ItemRef",
    "ItemRefresh",
    "LinkKind",
    "MAIN_TAG",
    "MediaStream",
    "Playback",
    "NpoSource",
    "PlaybackKind",
    "ProgramStatus",
    "ResolvedLink",
    "RssEpisodeType",
    "SearchNotice",
    "SearchResults",
    "SeasonRef",
    "CollectionDetails",
    "Site",
    "StreamMethod",
    "Source",
    "SourceProblem",
    "CookiesStatus",
    "UnknownSourceError",
    "VideoDetails",
    "MIN_NEWEST_EPISODES",
    "VideoFormat",
    "VideoFormats",
    "YtDlpSource",
    "all_sources",
    "collection_on_site",
    "get_source",
    "register",
    "sources_for",
    "named_site_for",
    "named_sites",
    "site_for",
]
