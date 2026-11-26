from ...contract import Access, ListOrder
from .other_sites import MEMBERS_KEY, OtherSites


class Floatplane(OtherSites):
    key = "floatplane"
    name = "Floatplane"
    initials = "FP"
    domains = ("floatplane.com",)
    # yt-dlp lists only a creator's channels on Floatplane, newest first.
    list_order = ListOrder.NEWEST_FIRST
    accesses = (Access(MEMBERS_KEY, "Subscribers only", "Only subscribers of the creator can watch this."),)
