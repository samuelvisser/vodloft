from ...contract import ListOrder
from .other_sites import OtherSites


class Rumble(OtherSites):
    key, name = "rumble", "Rumble"
    initials = "RU"
    domains = ("rumble.com",)
    # yt-dlp lists only channels on Rumble, newest first.
    list_order = ListOrder.NEWEST_FIRST
