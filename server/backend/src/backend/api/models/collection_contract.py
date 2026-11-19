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


class CollectionContractAPIRead(ResponseBase):
    """One collection type's words: for episodes of video, and for episodes of sound only, such as the tracks of a
    Music collection on Bandcamp."""

    type: CollectionType
    words: CollectionWordsAPIRead
    audio_words: CollectionWordsAPIRead
    downloads_by_season: bool
    """Downloads pick the collection's seasons; otherwise its newest episodes, by days or a number of episodes."""


class CollectionContractsAPIRead(ResponseBase):
    """Every collection type's contract, and VODLoft's own words where no type is meant."""

    words: CollectionWordsAPIRead
    types: list[CollectionContractAPIRead]
