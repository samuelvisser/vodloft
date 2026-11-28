from ...contract import AccountSignIn, ApiField, GuideStep, ListOrder, Names, SectionKind, SectionType, SignInKind
from .feed_section_type import YtdlpFeedSectionType
from .other_sites import OtherSites

ALBUM_LIST = "album"
PLAYLIST_LIST = "playlist"
SOUNDCLOUD_TOKEN = "token"


class SoundCloud(OtherSites):
    key = "soundcloud"
    name = "SoundCloud"
    initials = "SC"
    pitch = "Artists, albums and playlists"
    domains = ("soundcloud.com",)
    icon = "fab:soundcloud"
    audio_only = True
    creators = True
    # Its albums and playlists keep an order of their own, the first first.
    list_order = ListOrder.OLDEST_FIRST
    # Its apps share short links, which redirect to its pages.
    share_hosts = ("on.soundcloud.com",)
    # Its accounts, albums, playlists and tracks are found by name. Each search asks SoundCloud four times, or runs
    # yt-dlp when that fails, so it searches when asked instead of while the user types.
    searchable = True
    costly_search = True
    # An account may be a music artist or anyone else, such as a podcast; a Music collection calls it an artist.
    # An account has its Tracks, and its sets: albums and playlists, which SoundCloud tells apart. A track on its own
    # is a single.
    section_types = (
        YtdlpFeedSectionType("tracks", Names("track", "tracks"), "tracks"),
        SectionType(ALBUM_LIST, SectionKind.LIST, Names("album", "albums"), albums=True),
        SectionType(PLAYLIST_LIST, SectionKind.LIST, Names("playlist", "playlists")),
        SectionType("single", SectionKind.ITEM, Names("single", "singles")),
    )
    link_seasons = True
    channel_collection_names = Names("account", "accounts")
    # A set is an album or a playlist, which its link doesn't tell. SoundCloud says which when the set is looked up,
    # and VODLoft keeps that with the collection; this names a set it has not looked up.
    list_collection_names = Names.joined((Names("album", "albums"), Names("playlist", "playlists")))
    channel_season_names = Names("album", "albums")
    list_season_names = Names("group", "groups")
    # SoundCloud lets no other program sign in with a password, but its website keeps a token yt-dlp signs in with.
    account_sign_in = AccountSignIn(
        SignInKind.TOKEN,
        "Sign in with your SoundCloud account to download what only your account may play, such as your own "
        "private tracks or SoundCloud Go+ tracks.",
        (ApiField(SOUNDCLOUD_TOKEN, "Sign-in token", secret=True),),
        (
            GuideStep("Sign in on soundcloud.com in your browser.", "Open SoundCloud", "https://soundcloud.com/signin"),
            GuideStep(
                "Open the browser's developer tools (F12), go to Application (Storage in Firefox), then Cookies, "
                "https://soundcloud.com.",
            ),
            GuideStep("Copy the value of the cookie named oauth_token. It starts with 2-."),
        ),
    )
