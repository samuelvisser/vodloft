from ...contract import Names, SectionKind, SectionType
from .feed_section_type import YtdlpFeedSectionType
from .other_sites import CREATOR_PRESETS, OtherSites

ALBUM_LIST = "album"
PLAYLIST_LIST = "playlist"


class SoundCloud(OtherSites):
    key = "soundcloud"
    name = "SoundCloud"
    audio_only = True
    creators = True
    # An account may be a music artist or anyone else, such as a podcast; a Music collection calls it an artist.
    creator_presets = CREATOR_PRESETS
    # An account has its Tracks, and its sets: albums and playlists, which SoundCloud tells apart. A track on its own
    # is a single.
    section_types = (
        YtdlpFeedSectionType("tracks", Names("track", "tracks"), "tracks"),
        SectionType(ALBUM_LIST, SectionKind.LIST, Names("album", "albums"), albums=True),
        SectionType(PLAYLIST_LIST, SectionKind.LIST, Names("playlist", "playlists")),
        SectionType("single", SectionKind.ITEM, Names("single", "singles")),
    )
    link_seasons = True
    # What is in none of a collection's albums and playlists is its tracks.
    loose_season = "Tracks"
