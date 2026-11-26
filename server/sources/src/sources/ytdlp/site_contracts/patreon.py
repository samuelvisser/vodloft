from ...contract import LIST_TYPE, Access, CreatorTierAccess, ListOrder, Names, SectionKind, SectionType
from .feed_section_type import YtdlpFeedSectionType
from .other_sites import MEMBERS_KEY, OtherSites


class Patreon(OtherSites):
    key = "patreon"
    name = "Patreon"
    initials = "PA"
    domains = ("patreon.com",)
    icon = "fab:patreon"
    creators = True
    # A creator's posts, and their collections. Patreon calls its playlists collections, which is VODLoft's word for
    # something else, so VODLoft calls them playlists.
    section_types = (
        YtdlpFeedSectionType("posts", Names("post", "posts"), "posts"),
        SectionType(LIST_TYPE, SectionKind.LIST, Names("playlist", "playlists")),
    )
    link_seasons = True
    # Patreon signs the links to its pictures, and they stop working after a few weeks.
    pictures_expire = True
    # VODLoft lists a playlist's posts the first first, whichever order Patreon keeps it in.
    list_order = ListOrder.OLDEST_FIRST
    accesses = (Access(MEMBERS_KEY, "Patrons only", "Only the creator's patrons can watch this."),)
    # Each creator sets up tiers of their own.
    creator_tiers = CreatorTierAccess(
        "tier", "{name}", "Only patrons on the creator's “{name}” tier ({amount}) or higher can watch this.",
        "Patrons from {amount}", "Only the creator's patrons who pledge {amount} or more can watch this.",
        "Paid tier", "Only the creator's patrons on one of their paid tiers can watch this.",
    )
