from ...contract import CreatorSectionNames, ListNames, ListType
from .other_sites import CREATOR_PRESETS, OtherSites

ALBUM_LIST = "album"
PLAYLIST_LIST = "playlist"


class SoundCloud(OtherSites):
    key = "soundcloud"
    name = "SoundCloud"
    audio = True
    creators = True
    creator_label = "artist"
    creator_presets = CREATOR_PRESETS
    # An account's sets are its albums and its playlists, which SoundCloud tells apart.
    creator_sections = CreatorSectionNames("an album or playlist", "albums and playlists")
    # SoundCloud keeps an artist's albums apart from the playlists they put together.
    list_types = (
        ListType(ALBUM_LIST, CreatorSectionNames("an album", "albums"), albums=True),
        ListType(PLAYLIST_LIST, CreatorSectionNames("a playlist", "playlists")),
    )
    link_seasons = True
    # Outside a Music collection, such as a podcast's, its sets are playlists, and what is in none of them is its
    # tracks.
    list_names = ListNames("playlist", "playlists", "Tracks")
