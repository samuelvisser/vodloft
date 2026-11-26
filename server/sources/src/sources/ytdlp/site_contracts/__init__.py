"""The contracts of the sites yt-dlp downloads from: one per site VODLoft treats its own way, and ``OtherSites``
for every other site and for whatever a site's own contract leaves out. ``sites.site_of`` builds the ``Site``."""
from .bandcamp import Bandcamp
from .curiositystream import CuriosityStream
from .dailymotion import Dailymotion
from .dropout import Dropout
from .floatplane import Floatplane
from .instagram import Instagram
from .kick import Kick
from .named import NAMED
from .nebula import Nebula
from .niconico import Niconico
from .odysee import Odysee
from .feed_section_type import YtdlpFeedSectionType
from .other_sites import MEMBERS_KEY, PREMIUM_KEY, OtherSites
from .patreon import Patreon
from .peertube import PeerTube
from .rumble import Rumble
from .soundcloud import SoundCloud
from .tiktok import TikTok
from .twitch import Twitch
from .x import X
from .youtube import YouTube

CONTRACTS: dict[str, type[OtherSites]] = {contract.key: contract for contract in (
    YouTube, Twitch, X, Instagram, TikTok, SoundCloud, Bandcamp, Dailymotion, Kick, Nebula, Odysee, PeerTube, Niconico,
    Floatplane, CuriosityStream, Dropout, Patreon, Rumble, *NAMED,
)}

__all__ = ["CONTRACTS", "MEMBERS_KEY", "PREMIUM_KEY", "OtherSites", "YtdlpFeedSectionType"]
