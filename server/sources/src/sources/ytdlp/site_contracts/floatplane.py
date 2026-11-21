from ...contract import Access
from .other_sites import MEMBERS_KEY, OtherSites


class Floatplane(OtherSites):
    key = "floatplane"
    name = "Floatplane"
    domains = ("floatplane.com",)
    accesses = (Access(MEMBERS_KEY, "Subscribers only", "Only subscribers of the creator can watch this."),)
