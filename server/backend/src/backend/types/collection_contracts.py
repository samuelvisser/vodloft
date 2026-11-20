"""What VODLoft does differently by collection type, as a Site's contract does for its Site: what a Podcast, a Series
or a Music collection calls its seasons and episodes. Everything that names them, in the API and so in the UI, takes
its words from here."""
from __future__ import annotations

from dataclasses import dataclass

from sources import Names, Site

from .collection_types import CollectionType
from .local_media_profile_types import CollectionLocalMediaProfileScope as ProfileScope


@dataclass(frozen=True)
class CollectionWords:
    """What a collection calls its seasons and its episodes."""

    season: Names
    episode: Names


DEFAULT_WORDS = CollectionWords(Names("season", "seasons"), Names("episode", "episodes"))
"""VODLoft's words for seasons and episodes where no collection type is meant, and those of a type that sets none."""


@dataclass(frozen=True)
class CollectionContract:
    """One collection type and what is special about it. The field defaults are VODLoft's fallback for every
    type; each type's contract below sets only what differs from them."""

    type: CollectionType
    words: CollectionWords = DEFAULT_WORDS
    """What its seasons and episodes are called, when they are video."""
    audio_words: CollectionWords | None = None
    """What they are called when they are sound only, such as the tracks of a Music collection on a Site with sound
    only or the files of a profile for Music tracks; the same as ``words`` unless the contract sets it."""

    creator_names: Names | None = None
    """What a collection of the type calls the creator behind it, whatever their Site calls its creators, such as
    artist for Music; when unset, the Site's word (``creator_names_on``)."""

    loose_season: str | None = None
    """What VODLoft calls the season of the episodes in none of a collection's link seasons, such as Singles for
    Music, whatever the Site calls it; when unset, the Site's name (``loose_season_on``)."""

    media_are_episodes: bool = False
    """What its Site's lists hold is called by the type's episode word, such as an artist's music videos; otherwise by
    the Site's word for its media, such as videos (``media_names_on``)."""
    site_order: bool = False
    """Its link seasons keep the order its Site gives the lists, as an artist's albums do, instead of by date."""
    album_lists: bool = False
    """It takes the kinds of list that best describe albums, where its Site has them, and skips the others, such as an
    artist's SoundCloud playlists."""

    profile_scope: ProfileScope = ProfileScope.BOTH
    """What a new Local Media Profile made for a collection of the type keeps, such as Podcasts."""
    audio_profile_scope: ProfileScope | None = None
    """What it keeps when it is made for sound, such as Music tracks; the same as ``profile_scope`` unless set."""

    downloads_by_season: bool = True
    """Downloads pick the collection's seasons, as for a series or an artist's albums; otherwise its newest episodes,
    by a number of days or of episodes, as for a podcast."""

    def __post_init__(self) -> None:
        if self.audio_words is None:
            object.__setattr__(self, "audio_words", self.words)
        if self.audio_profile_scope is None:
            object.__setattr__(self, "audio_profile_scope", self.profile_scope)

    @property
    def profile_scopes(self) -> tuple[ProfileScope, ...]:
        """What a Local Media Profile can keep to be offered for a collection of the type, such as Both or Podcasts."""
        return tuple(scope for scope in ProfileScope if self.type.value in scope.collection_types())

    def creator_names_on(self, site: Site) -> Names:
        """What a collection of the type on ``site`` calls the creator behind it: the type's word, or the Site's."""
        return self.creator_names or site.creator_names

    def loose_season_on(self, site: Site) -> str:
        """What a collection of the type on ``site`` calls the season of what is in none of its link seasons."""
        return self.loose_season or site.loose_season

    def media_names_on(self, site: Site, audio: bool | None = None) -> Names:
        """What a collection of the type on ``site`` calls what the Site's lists hold: its episodes, or the Site's
        media."""
        return self.words_for(site.audio_only if audio is None else audio).episode if self.media_are_episodes else site.media_names

    def words_for(self, audio: bool = False) -> CollectionWords:
        """Its words for episodes of video, or with ``audio`` for those of sound only."""
        return self.audio_words if audio else self.words


PODCAST = CollectionContract(CollectionType.PODCAST, profile_scope=ProfileScope.PODCAST, downloads_by_season=False)
"""A podcast, whose newest episodes are what is downloaded."""

SERIES = CollectionContract(CollectionType.SERIES, profile_scope=ProfileScope.SERIES)
"""A series' seasons and episodes, which are what VODLoft calls them everywhere."""

MUSIC = CollectionContract(
    CollectionType.MUSIC,
    words=CollectionWords(Names("album", "albums"), Names("music video", "music videos")),
    audio_words=CollectionWords(Names("album", "albums"), Names("track", "tracks")),
    creator_names=Names("artist", "artists"),
    loose_season="Singles",
    media_are_episodes=True,
    site_order=True,
    album_lists=True,
    profile_scope=ProfileScope.MUSIC_VIDEOS,
    audio_profile_scope=ProfileScope.MUSIC_TRACKS,
)
"""An artist's music: each season an album, each episode a music video, or a track where it is sound only. Its
creator is an artist on every Site, and what is in none of its albums is Singles."""

CONTRACTS = {contract.type: contract for contract in (PODCAST, SERIES, MUSIC)}


def collection_contract(collection_type: CollectionType | str) -> CollectionContract:
    """The contract of a collection type, given as the type or its stored value."""
    return CONTRACTS[CollectionType(collection_type)]
