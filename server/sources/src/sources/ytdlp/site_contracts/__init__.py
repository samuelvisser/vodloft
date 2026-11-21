"""The contracts of the sites yt-dlp downloads from: one per site VODLoft treats its own way, and ``OtherSites``
for every other site and for whatever a site's own contract leaves out. ``sites.site_of`` builds the ``Site``."""
from .bandcamp import Bandcamp
from .floatplane import Floatplane
from .instagram import Instagram
from .named import NAMED
from .niconico import Niconico
from .feed_section_type import YtdlpFeedSectionType
from .other_sites import MEMBERS_KEY, PREMIUM_KEY, OtherSites
from .soundcloud import SoundCloud
from .tiktok import TikTok
from .twitch import Twitch
from .x import X
from .youtube import YouTube

CONTRACTS: dict[str, type[OtherSites]] = {contract.key: contract for contract in (
    YouTube, Twitch, X, Instagram, TikTok, SoundCloud, Bandcamp, Niconico, Floatplane, *NAMED,
)}

__all__ = ["CONTRACTS", "MEMBERS_KEY", "PREMIUM_KEY", "OtherSites", "YtdlpFeedSectionType"]
