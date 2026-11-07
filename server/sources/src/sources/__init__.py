"""VODLoft Sources.

A Source is everything VODLoft knows about one service. Each lives in its own
subpackage (``sources.dailywire``); the rest of VODLoft reaches it through the
contract in ``sources.contract`` and the registry below.
"""
from .contract import ANY_DOMAIN, ApiKeyRejected, ApiQuotaShare, ApiStatus, EpisodeMedia, EpisodePublishStatus, EpisodeTag, PublishStatusLabel, Feature, ItemRef, ItemRefresh, MAIN_TAG, MIN_NEWEST_EPISODES, LinkKind, LinkPreview, LiveStream, MediaStream, MediaTracks, Playback, PlaybackKind, ProgramStatus, ResolvedLink, RssEpisodeType, SearchNotice, SearchResults, SeasonRef, CollectionDetails, CookiesStatus, DownloadOptions, Site, SiteSetting, SiteSettings, Source, SourceProblem, SponsorBlockSegment, StreamMethod, UpgradeChecks, UpgradeImprovement, UpgradeOffer, VIDEO_HEIGHTS, VideoDetails, VideoFormat, VideoFormats, names_a_podcast
from .registry import UnknownSourceError, all_sources, collection_on_site, get_source, named_site_for, named_sites, register, site_for, site_of, source_site, sources_for
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
    "VIDEO_HEIGHTS",
    "ANY_DOMAIN",
    "ApiKeyRejected",
    "ApiQuotaShare",
    "ApiStatus",
    "DAILYWIRE",
    "DailyWireSource",
    "DownloadOptions",
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
    "LiveStream",
    "MediaTracks",
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
    "SiteSetting",
    "SiteSettings",
    "StreamMethod",
    "Source",
    "SourceProblem",
    "CookiesStatus",
    "UnknownSourceError",
    "VideoDetails",
    "MIN_NEWEST_EPISODES",
    "UpgradeChecks",
    "UpgradeImprovement",
    "VideoFormat",
    "VideoFormats",
    "YtDlpSource",
    "names_a_podcast",
    "all_sources",
    "collection_on_site",
    "get_source",
    "register",
    "sources_for",
    "named_site_for",
    "named_sites",
    "site_for",
    "site_of",
    "source_site",
]
