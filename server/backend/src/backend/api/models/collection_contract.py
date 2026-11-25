"""What each collection type calls its seasons and episodes, from the collection contracts, so every page names them
the same way."""
from __future__ import annotations

from backend.api.models.base import ResponseBase
from backend.api.models.source import NamesAPIRead
from backend.types.collection_types import CollectionType


class CollectionWordsAPIRead(ResponseBase):
    """What a collection calls its seasons and its episodes."""

    season: NamesAPIRead
    episode: NamesAPIRead
    in_season: str
    """The word for being in one of its seasons, such as on for a track on an album."""
    numbered_in_season: bool = False
    """An episode is named by its number in its season alone, as an album's tracks are: Track 3, not S01E03."""


class CollectionContractAPIRead(ResponseBase):
    """One collection type's words: for episodes of video, and for episodes of sound only, such as the tracks of a
    Music collection on Bandcamp."""

    type: CollectionType
    words: CollectionWordsAPIRead
    audio_words: CollectionWordsAPIRead
    creator_names: NamesAPIRead | None
    """What a collection of the type calls the creator behind it, such as artist; none where it is the Site's word."""
    loose_season: str | None
    """What the season of what is in none of a collection's lists is called, such as Singles; none for the Site's."""
    profile_scope: str
    """What a new Local Media Profile for a collection of the type keeps, such as podcast."""
    profile_scopes: list[str]
    """What a Local Media Profile can keep to be offered for a collection of the type."""
    downloads_by_season: bool
    """Downloads pick the collection's seasons; otherwise its newest episodes, by days or a number of episodes."""


class CollectionContractsAPIRead(ResponseBase):
    """Every collection type's contract, and VODLoft's own words where no type is meant."""

    words: CollectionWordsAPIRead
    types: list[CollectionContractAPIRead]
