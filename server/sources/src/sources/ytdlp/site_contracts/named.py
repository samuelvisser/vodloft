"""Sites whose own contract only names them the way most people know them."""
from .other_sites import OtherSites


class BBC(OtherSites):
    key, name = "bbc", "BBC"
    domains = ("bbc.co.uk", "bbc.com")


class Bilibili(OtherSites):
    key, name = "bilibili", "Bilibili"
    domains = ("bilibili.com", "b23.tv")


class BitChute(OtherSites):
    key, name = "bitchute", "BitChute"
    domains = ("bitchute.com",)


class Dailymotion(OtherSites):
    key, name = "dailymotion", "Dailymotion"
    domains = ("dailymotion.com", "dai.ly")


class Facebook(OtherSites):
    key, name = "facebook", "Facebook"
    domains = ("facebook.com", "fb.watch")


class Instagram(OtherSites):
    key, name = "instagram", "Instagram"
    domains = ("instagram.com",)


class Kick(OtherSites):
    key, name = "kick", "Kick"
    domains = ("kick.com",)


class Nebula(OtherSites):
    key, name = "nebula", "Nebula"
    domains = ("nebula.tv",)


class Odysee(OtherSites):
    key, name = "odysee", "Odysee"
    domains = ("odysee.com",)


class Patreon(OtherSites):
    key, name = "patreon", "Patreon"
    domains = ("patreon.com",)


class PeerTube(OtherSites):
    # Every PeerTube server has a domain of its own, so PeerTube has none.
    key, name = "peertube", "PeerTube"


class Reddit(OtherSites):
    key, name = "reddit", "Reddit"
    domains = ("reddit.com", "redd.it")


class Rumble(OtherSites):
    key, name = "rumble", "Rumble"
    domains = ("rumble.com",)


class TikTok(OtherSites):
    key, name = "tiktok", "TikTok"
    domains = ("tiktok.com",)


class Twitch(OtherSites):
    key, name = "twitch", "Twitch"
    domains = ("twitch.tv",)


class X(OtherSites):
    key, name = "twitter", "X"
    domains = ("x.com", "twitter.com")


class Vimeo(OtherSites):
    key, name = "vimeo", "Vimeo"
    domains = ("vimeo.com",)


NAMED = (BBC, Bilibili, BitChute, Dailymotion, Facebook, Instagram, Kick, Nebula, Odysee, Patreon, PeerTube, Reddit, Rumble, TikTok, Twitch, X, Vimeo)
