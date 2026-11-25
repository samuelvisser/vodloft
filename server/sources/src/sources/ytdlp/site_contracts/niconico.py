from ...contract import Access
from .other_sites import MEMBERS_KEY, PREMIUM_KEY, OtherSites


class Niconico(OtherSites):
    key = "niconico"
    name = "Niconico"
    initials = "NC"
    domains = ("nicovideo.jp",)
    # Niconico's official search API finds videos by name, the most watched first. It has no search of channels or
    # users.
    searchable = True
    search_note = "Niconico's search only finds videos. To add a channel, user or mylist, paste its link on Add media."
    accesses = (
        Access(MEMBERS_KEY, "Channel members only", "Only members of the channel can watch this."),
        Access(PREMIUM_KEY, "Niconico Premium", "Only Niconico Premium members can watch this."),
    )
