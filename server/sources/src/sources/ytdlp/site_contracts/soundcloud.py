from ...contract import Names, SeasonNames, SectionKind, SectionType
from .other_sites import CREATOR_PRESETS, OtherSites

ALBUM_LIST = "album"
PLAYLIST_LIST = "playlist"


class SoundCloud(OtherSites):
    key = "soundcloud"
    name = "SoundCloud"
    audio_only = True
    creators = True
    creator_label = "artist"
    creator_presets = CREATOR_PRESETS
    # An account has its tracks, and its sets: albums and playlists, which SoundCloud tells apart. A track on its own
    # is a single.
    section_types = (
        SectionType("feed", SectionKind.FEED, Names("feed", "feeds")),
        SectionType(ALBUM_LIST, SectionKind.LIST, Names("album", "albums"), albums=True),
        SectionType(PLAYLIST_LIST, SectionKind.LIST, Names("playlist", "playlists")),
        SectionType("single", SectionKind.ITEM, Names("single", "singles")),
    )
    link_seasons = True
    # What is in none of a collection's albums and playlists is its tracks.
    season_names = SeasonNames("Tracks")
