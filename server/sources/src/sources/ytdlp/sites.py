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
from functools import cache
from pathlib import Path

from ..contract import DownloadOptions, Site, domain_site
from ..cookies import site_cookies
from ..registry import named_site_for
from .site_contracts import CONTRACTS, MEMBERS_KEY, PREMIUM_KEY, OtherSites
from .site_contracts.other_sites import SITE_FIELDS
from .site_contracts.soundcloud import ALBUM_LIST, PLAYLIST_LIST

__all__ = [
    "ALBUM_LIST", "MEMBERS_KEY", "PLAYLIST_LIST", "PREMIUM_KEY", "api_key_sites", "cookies_for", "download_options", "site_for", "site_of",
]

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
    domain = domain_site(url)
    if extractor is None or extractor.ie_key() == "Generic":
        # A page only the generic extractor handles is a Site of its own per domain, with what OtherSites offers.
        return site_of(domain.key, domain.name)
    return site_of(_family(extractor), domain.name)


def cookies_for(url: str, use: bool = True) -> Path | None:
    """The cookies file of the link's Site, which yt-dlp signs in with there; ``use`` False leaves it out.

    A Site some Source is made for, such as NPO Start, has its cookies file whichever Source fetches it,
    and a Site that takes no cookies, such as The Daily Wire, never gets one.
    """
    site = named_site_for(url) or site_for(url)
    return site_cookies(site.key) if use and site.takes_cookies else None


@cache
def site_of(key: str, host: str | None = None) -> Site:
    """The Site with the key, as yt-dlp fetches it: its own contract, and ``OtherSites`` for whatever that leaves out,
    or for a site without a contract. A link's host names a Site without a name of its own. A contract never changes,
    so each Site is built once per key and host."""
    contract = CONTRACTS.get(key, OtherSites)
    values = {name: getattr(contract, name) for name in SITE_FIELDS if hasattr(contract, name)}
    values["accesses"] = _accesses(contract)
    return Site(key, contract.name or host or key, (host,) if host else (), **values)


def api_key_sites() -> tuple[Site, ...]:
    """The Sites yt-dlp's API key is for, such as YouTube for the YouTube Data API key, with the domain yt-dlp names
    them by."""
    return tuple(site_of(key, f"{key}.com") for key, contract in sorted(CONTRACTS.items()) if getattr(contract, "takes_api_key", False))


def _accesses(contract: type[OtherSites]):
    """The site's own names for the accesses yt-dlp tells, and the general ones for those it has none for."""
    own = contract.accesses
    return own + tuple(access for access in OtherSites.accesses if access.key not in {mine.key for mine in own})


def download_options() -> DownloadOptions:
    """What any Site yt-dlp downloads from offers: the quality choices and subtitles, and an HLS bundle from some."""
    return DownloadOptions.combined((OtherSites.downloads, *(contract.downloads for contract in CONTRACTS.values())))
