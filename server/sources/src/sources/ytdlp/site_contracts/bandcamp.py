from ...contract import Names, SeasonNames, SectionKind, SectionType
from .other_sites import CREATOR_PRESETS, OtherSites


class Bandcamp(OtherSites):
    key = "bandcamp"
    name = "Bandcamp"
    audio_only = True
    creators = True
    creator_label = "artist"
    creator_presets = CREATOR_PRESETS
    # An artist has albums, and tracks of their own: singles.
    section_types = (
        SectionType("album", SectionKind.LIST, Names("album", "albums")),
        SectionType("single", SectionKind.ITEM, Names("single", "singles")),
    )
    # An artist's albums are their playlists.
    link_seasons = True
    # What is in none of a collection's albums is its tracks.
    season_names = SeasonNames("Tracks")
