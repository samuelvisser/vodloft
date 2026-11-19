"""Sites whose own contract only names them the way most people know them."""
from .other_sites import OtherSites


class BBC(OtherSites):
    key, name = "bbc", "BBC"


class Bilibili(OtherSites):
    key, name = "bilibili", "Bilibili"


class BitChute(OtherSites):
    key, name = "bitchute", "BitChute"


class Dailymotion(OtherSites):
    key, name = "dailymotion", "Dailymotion"


class Facebook(OtherSites):
    key, name = "facebook", "Facebook"


class Instagram(OtherSites):
    key, name = "instagram", "Instagram"


class Kick(OtherSites):
    key, name = "kick", "Kick"


class Nebula(OtherSites):
    key, name = "nebula", "Nebula"


class Odysee(OtherSites):
    key, name = "odysee", "Odysee"


class Patreon(OtherSites):
    key, name = "patreon", "Patreon"


class PeerTube(OtherSites):
    key, name = "peertube", "PeerTube"


class Reddit(OtherSites):
    key, name = "reddit", "Reddit"


class Rumble(OtherSites):
    key, name = "rumble", "Rumble"


class TikTok(OtherSites):
    key, name = "tiktok", "TikTok"


class Twitch(OtherSites):
    key, name = "twitch", "Twitch"


class X(OtherSites):
    key, name = "twitter", "X"


class Vimeo(OtherSites):
    key, name = "vimeo", "Vimeo"


NAMED = (BBC, Bilibili, BitChute, Dailymotion, Facebook, Instagram, Kick, Nebula, Odysee, Patreon, PeerTube, Reddit, Rumble, TikTok, Twitch, X, Vimeo)
