"""Sites whose own contract only names them the way most people know them."""
from .other_sites import OtherSites


class BBC(OtherSites):
    key, name = "bbc", "BBC"
    initials = "BB"
    domains = ("bbc.co.uk", "bbc.com")


class Bilibili(OtherSites):
    key, name = "bilibili", "Bilibili"
    initials = "BL"
    domains = ("bilibili.com", "b23.tv")
    icon = "fab:bilibili"


class BitChute(OtherSites):
    key, name = "bitchute", "BitChute"
    initials = "BT"
    domains = ("bitchute.com",)


class Dailymotion(OtherSites):
    key, name = "dailymotion", "Dailymotion"
    initials = "DM"
    domains = ("dailymotion.com", "dai.ly")
    icon = "fab:dailymotion"


class Facebook(OtherSites):
    key, name = "facebook", "Facebook"
    initials = "FB"
    domains = ("facebook.com", "fb.watch")
    icon = "fab:facebook"


class Kick(OtherSites):
    key, name = "kick", "Kick"
    initials = "KI"
    domains = ("kick.com",)


class Odysee(OtherSites):
    key, name = "odysee", "Odysee"
    initials = "OD"
    domains = ("odysee.com",)
    icon = "fab:odysee"


class Patreon(OtherSites):
    key, name = "patreon", "Patreon"
    initials = "PA"
    domains = ("patreon.com",)
    icon = "fab:patreon"


class PeerTube(OtherSites):
    # Every PeerTube server has a domain of its own, so PeerTube has none.
    key, name = "peertube", "PeerTube"
    initials = "PT"


class Reddit(OtherSites):
    key, name = "reddit", "Reddit"
    initials = "RD"
    domains = ("reddit.com", "redd.it")
    icon = "fab:reddit"


class Rumble(OtherSites):
    key, name = "rumble", "Rumble"
    initials = "RU"
    domains = ("rumble.com",)


class Vimeo(OtherSites):
    key, name = "vimeo", "Vimeo"
    initials = "VM"
    domains = ("vimeo.com",)
    icon = "fab:vimeo-v"
    pitch = "Channels, showcases and videos"


NAMED = (BBC, Bilibili, BitChute, Dailymotion, Facebook, Kick, Odysee, Patreon, PeerTube, Reddit, Rumble, Vimeo)
