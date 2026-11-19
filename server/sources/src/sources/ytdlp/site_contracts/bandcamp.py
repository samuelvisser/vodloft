from ...contract import CreatorSectionNames
from .other_sites import CREATOR_PRESETS, OtherSites


class Bandcamp(OtherSites):
    key = "bandcamp"
    name = "Bandcamp"
    audio = True
    creators = True
    creator_label = "artist"
    creator_presets = CREATOR_PRESETS
    # An artist's albums are their playlists.
    creator_sections = CreatorSectionNames("an album", "albums")
    link_seasons = True
