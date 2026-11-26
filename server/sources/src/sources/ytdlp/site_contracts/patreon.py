from ...contract import Access
from .other_sites import MEMBERS_KEY, OtherSites


class Patreon(OtherSites):
    key = "patreon"
    name = "Patreon"
    initials = "PA"
    domains = ("patreon.com",)
    icon = "fab:patreon"
    accesses = (Access(MEMBERS_KEY, "Patrons only", "Only the creator's patrons can watch this."),)
