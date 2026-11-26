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


class Facebook(OtherSites):
    key, name = "facebook", "Facebook"
    initials = "FB"
    domains = ("facebook.com", "fb.watch")
    icon = "fab:facebook"


class Reddit(OtherSites):
    key, name = "reddit", "Reddit"
    initials = "RD"
    domains = ("reddit.com", "redd.it")
    icon = "fab:reddit"


class Vimeo(OtherSites):
    key, name = "vimeo", "Vimeo"
    initials = "VM"
    domains = ("vimeo.com",)
    icon = "fab:vimeo-v"
    pitch = "Channels, showcases and videos"


NAMED = (BBC, Bilibili, BitChute, Facebook, Reddit, Vimeo)
