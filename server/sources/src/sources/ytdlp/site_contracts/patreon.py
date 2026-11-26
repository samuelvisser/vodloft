from ...contract import Access
from .other_sites import MEMBERS_KEY, OtherSites


class Patreon(OtherSites):
    key = "patreon"
    name = "Patreon"
    initials = "PA"
    domains = ("patreon.com",)
    icon = "fab:patreon"
    # A creator's page lists their posts newest first.
    lists_in_order = False
    accesses = (Access(MEMBERS_KEY, "Patrons only", "Only the creator's patrons can watch this."),)
