from ...contract import Access
from .other_sites import MEMBERS_KEY, PREMIUM_KEY, OtherSites


class Niconico(OtherSites):
    key = "niconico"
    name = "Niconico"
    domains = ("nicovideo.jp",)
    accesses = (
        Access(MEMBERS_KEY, "Channel members only", "Only members of the channel can watch this."),
        Access(PREMIUM_KEY, "Niconico Premium", "Only Niconico Premium members can watch this."),
    )
