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

from ..contract import Site, StreamMethod, domain_site, link_host

# How VODLoft names the sites most people use; any other Site is named after its domain.
_NAMES = {
    "bandcamp": "Bandcamp", "bbc": "BBC", "bilibili": "Bilibili", "bitchute": "BitChute", "dailymotion": "Dailymotion",
    "facebook": "Facebook", "instagram": "Instagram", "kick": "Kick", "nebula": "Nebula", "niconico": "Niconico",
    "odysee": "Odysee", "patreon": "Patreon", "peertube": "PeerTube", "reddit": "Reddit", "rumble": "Rumble",
    "soundcloud": "SoundCloud", "tiktok": "TikTok", "twitch": "Twitch", "twitter": "X", "vimeo": "Vimeo",
    "youtube": "YouTube",
}
# Creators keep changing titles and thumbnails for days, and YouTube tests them for up to two weeks.
_REFRESH_INTERVALS = {"youtube": "30m,2h,6h,24h,3d,7d,14d"}
# How RSS feeds can stream each Site without downloading first. Each needs its streams checked against
# podcast apps before it is added. YouTube only offers its 360p MP4 and M4A audio as plain files.
_STREAM_METHODS = {"youtube": frozenset({StreamMethod.FILE})}
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
        return domain_site(url)
    host = domain_site(url).name
    key = _family(extractor)
    return Site(key, _NAMES.get(key, host), (host,), _REFRESH_INTERVALS.get(key), stream_methods=_STREAM_METHODS.get(key, frozenset()))
