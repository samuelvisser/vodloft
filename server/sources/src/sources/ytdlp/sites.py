"""The Site of a link, from the yt-dlp extractor that would handle it.

yt-dlp has no Site of its own, but it keeps the extractors of one site together
in one module: ``youtube`` holds the extractors of videos, channels and
playlists, and their link patterns already cover every domain of the site. That
module's name is the Site's key. A page only the generic extractor handles is a
Site of its own per domain.

Telling the extractor needs no network request, only VODLoft's own copy of yt-dlp.
"""
from __future__ import annotations

import threading

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from ..contract import (
    DownloadOptions, Site, SiteSetting, SiteSettings, StreamMethod, UpgradeChecks, UpgradeImprovement, domain_site, link_host,
)
from ..cookies import site_cookies
from ..registry import named_site_for

# How VODLoft names the sites most people use; any other Site is named after its domain.
_NAMES = {
    "bandcamp": "Bandcamp", "bbc": "BBC", "bilibili": "Bilibili", "bitchute": "BitChute", "dailymotion": "Dailymotion",
    "facebook": "Facebook", "instagram": "Instagram", "kick": "Kick", "nebula": "Nebula", "niconico": "Niconico",
    "odysee": "Odysee", "patreon": "Patreon", "peertube": "PeerTube", "reddit": "Reddit", "rumble": "Rumble",
    "soundcloud": "SoundCloud", "tiktok": "TikTok", "twitch": "Twitch", "twitter": "X", "vimeo": "Vimeo",
    "youtube": "YouTube",
}
# How RSS feeds can stream each Site without downloading first. Each needs its streams checked against
# podcast apps before it is added. YouTube has its 360p MP4 with sound as one file, and every other
# resolution as separate H.264 video and M4A audio, which VODLoft lists in an HLS playlist or joins.
# Above 1080p, YouTube only has VP9 and AV1, which podcast apps often cannot play. Its links play
# for any address, so apps can be sent straight to them.
_STREAM_METHODS = {"youtube": frozenset({StreamMethod.FILE, StreamMethod.HLS, StreamMethod.LIVE})}
_STREAM_VIDEO_HEIGHTS = {"youtube": (360, 720, 1080)}
_STREAM_FILE_HEIGHTS = {"youtube": 360}
_STREAM_PROXY_CHOICE = {"youtube"}
# The Sites whose separate H.264 video and M4A audio Local Media Profiles can keep as an HLS bundle.
_HLS_DOWNLOADS = {"youtube"}
_API_KEY_SITES = {"youtube"}
"""The Sites yt-dlp's API key is for: the YouTube Data API key."""
# yt-dlp tells a video's resolutions, codecs and subtitles on every site; SponsorBlock only has YouTube's videos.
_UPGRADE_CHECKS = UpgradeChecks((UpgradeImprovement.RESOLUTION, UpgradeImprovement.SUBTITLES, UpgradeImprovement.CODEC))
_SITE_UPGRADE_CHECKS = {"youtube": UpgradeChecks(
    (UpgradeImprovement.RESOLUTION, UpgradeImprovement.SPONSORBLOCK, UpgradeImprovement.SUBTITLES, UpgradeImprovement.CODEC),
)}
_SITE_SETTINGS = {"youtube": SiteSettings(
    # SponsorBlock only has YouTube's videos.
    shows=frozenset({SiteSetting.SPONSORBLOCK, SiteSetting.SPONSORBLOCK_SEGMENTS}),
    presets=MappingProxyType({
        # Creators keep changing titles and thumbnails for days, and YouTube tests them for up to two weeks.
        SiteSetting.METADATA_REFRESH: "30m,2h,6h,24h,3d,7d,14d",
        SiteSetting.UPGRADE_IMPROVEMENTS: [UpgradeImprovement.RESOLUTION.value, UpgradeImprovement.SPONSORBLOCK.value],
    }),
)}
_PREFIX = "yt_dlp.extractor."
_extractors: list | None = None
_lock = threading.Lock()


def _extractor_classes() -> list:
    """yt-dlp's extractors in the order it tries them, the generic one last. Loading them takes a second or two, once."""
    global _extractors
    with _lock:
        if _extractors is None:
            from yt_dlp.extractor import gen_extractor_classes

            _extractors = list(gen_extractor_classes())
        return _extractors


def _family(extractor) -> str:
    """The extractor's module, without the module's own parts: ``yt_dlp.extractor.youtube._tab`` is ``youtube``."""
    module = str(getattr(extractor, "_module", "") or extractor.__module__)
    if module.startswith(_PREFIX) and module != f"{_PREFIX}lazy_extractors":
        return module.removeprefix(_PREFIX).split(".")[0].lower()
    return str(extractor.IE_NAME).split(":")[0].lower()


def site_for(url: str) -> Site:
    extractor = next((candidate for candidate in _extractor_classes() if candidate.suitable(url)), None)
    if extractor is None or extractor.ie_key() == "Generic":
        return replace(domain_site(url), upgrade_checks=_UPGRADE_CHECKS)
    host = domain_site(url).name
    return site_of(_family(extractor), host)


def cookies_for(url: str, use: bool = True) -> Path | None:
    """The cookies file of the link's Site, which yt-dlp signs in with there; ``use`` False leaves it out.

    A Site some Source is made for, such as NPO Start, has its cookies file whichever Source fetches it,
    and a Site that takes no cookies, such as The Daily Wire, never gets one.
    """
    site = named_site_for(url) or site_for(url)
    return site_cookies(site.key) if use and site.takes_cookies else None


def site_of(key: str, host: str | None = None) -> Site:
    """The Site with the key, as yt-dlp fetches it; a link's host names a Site without a name of its own."""
    return Site(
        key, _NAMES.get(key, host or key), (host,) if host else (), stream_methods=_STREAM_METHODS.get(key, frozenset()),
        stream_video_heights=_STREAM_VIDEO_HEIGHTS.get(key, ()), stream_file_height=_STREAM_FILE_HEIGHTS.get(key),
        stream_proxy_choice=key in _STREAM_PROXY_CHOICE,
        downloads=_downloads(key), upgrade_checks=_SITE_UPGRADE_CHECKS.get(key, _UPGRADE_CHECKS),
        settings=_SITE_SETTINGS.get(key, SiteSettings()), takes_api_key=key in _API_KEY_SITES,
    )


def _downloads(key: str) -> DownloadOptions:
    return DownloadOptions(hls_bundle=True) if key in _HLS_DOWNLOADS else DownloadOptions()


def download_options() -> DownloadOptions:
    """What any Site yt-dlp downloads from offers: the defaults, and an HLS bundle from some."""
    return DownloadOptions.combined((DownloadOptions(), *(_downloads(key) for key in _HLS_DOWNLOADS)))
