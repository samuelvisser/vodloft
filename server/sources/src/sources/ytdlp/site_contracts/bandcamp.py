from ...contract import ListOrder, Names, SectionKind, SectionType
from .other_sites import OtherSites


class Bandcamp(OtherSites):
    key = "bandcamp"
    name = "Bandcamp"
    initials = "BC"
    domains = ("bandcamp.com",)
    icon = "fab:bandcamp"
    audio_only = True
    creators = True
    # Its albums keep an order of their own, the first first.
    list_order = ListOrder.OLDEST_FIRST
    creator_names = Names("artist", "artists")
    # An artist has albums, and tracks of their own: singles.
    section_types = (
        SectionType("album", SectionKind.LIST, Names("album", "albums")),
        SectionType("single", SectionKind.ITEM, Names("single", "singles")),
    )
    # An artist's albums are their playlists.
    link_seasons = True
