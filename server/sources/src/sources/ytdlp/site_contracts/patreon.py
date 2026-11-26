from ...contract import LIST_TYPE, Access, ListOrder, Names, SectionKind, SectionType
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
    pledge_access = Access("pledge", "Patrons from {amount}", "Only the creator's patrons who pledge {amount} or more can watch this.")
