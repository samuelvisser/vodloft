"""How yt-dlp fetches, on each site, what that site's contract says it has: one implementation per site VODLoft
treats its own way, and ``OtherSitesImplementation`` for every other site. Each answers for the section types of its
site's contract by their keys. Only the yt-dlp Source uses them."""
from __future__ import annotations

from .artists import BandcampImplementation, SoundCloudImplementation
from .dailymotion import DailymotionImplementation
from .kick import KickImplementation
from .nebula import NebulaImplementation
from .niconico import NiconicoImplementation
from .odysee import OdyseeImplementation
from .other_sites import OtherSitesImplementation, Read
from .peertube import PeerTubeImplementation
from .tiktok import TikTokImplementation
from .twitch import TwitchImplementation
from .youtube import YouTubeImplementation

IMPLEMENTATIONS: dict[str, type[OtherSitesImplementation]] = {implementation.key: implementation for implementation in (
    YouTubeImplementation, TwitchImplementation, TikTokImplementation, SoundCloudImplementation, BandcampImplementation,
    DailymotionImplementation, KickImplementation, NebulaImplementation, NiconicoImplementation, OdyseeImplementation,
    PeerTubeImplementation,
)}

__all__ = ["IMPLEMENTATIONS", "OtherSitesImplementation", "Read"]
