"""Sites whose own contract only names them the way most people know them, and what they call a locked video."""
from ...contract import Access
from .other_sites import MEMBERS_KEY, OtherSites


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


class Facebook(OtherSites):
    key, name = "facebook", "Facebook"
    initials = "FB"
    domains = ("facebook.com", "fb.watch")
    icon = "fab:facebook"


class Patreon(OtherSites):
    key, name = "patreon", "Patreon"
    initials = "PA"
    domains = ("patreon.com",)
    icon = "fab:patreon"
    accesses = (Access(MEMBERS_KEY, "Patrons only", "Only the creator's patrons can watch this."),)


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


NAMED = (BBC, Bilibili, BitChute, Facebook, Patreon, Reddit, Rumble, Vimeo)
