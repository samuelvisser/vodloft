"""What VODLoft does differently by collection type, as a Site's contract does for its Site: what a Podcast, a Series
or a Music collection calls its seasons and episodes. Everything that names them, in the API and so in the UI, takes
its words from here."""
from __future__ import annotations

from dataclasses import dataclass

from sources import Names

from .collection_types import CollectionType


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

    def __post_init__(self) -> None:
        if self.audio_words is None:
            object.__setattr__(self, "audio_words", self.words)

    def words_for(self, audio: bool = False) -> CollectionWords:
        """Its words for episodes of video, or with ``audio`` for those of sound only."""
        return self.audio_words if audio else self.words


PODCAST = CollectionContract(CollectionType.PODCAST)
"""A podcast's episodes, which are what VODLoft calls them everywhere."""

SERIES = CollectionContract(CollectionType.SERIES)
"""A series' seasons and episodes, which are what VODLoft calls them everywhere."""

MUSIC = CollectionContract(
    CollectionType.MUSIC,
    words=CollectionWords(Names("album", "albums"), Names("music video", "music videos")),
    audio_words=CollectionWords(Names("album", "albums"), Names("track", "tracks")),
)
"""An artist's music: each season an album, each episode a music video, or a track where it is sound only."""

CONTRACTS = {contract.type: contract for contract in (PODCAST, SERIES, MUSIC)}


def collection_contract(collection_type: CollectionType | str) -> CollectionContract:
    """The contract of a collection type, given as the type or its stored value."""
    return CONTRACTS[CollectionType(collection_type)]
