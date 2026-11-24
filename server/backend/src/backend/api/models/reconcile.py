"""The Move action of a collection and of one episode."""
from __future__ import annotations

from typing import Optional

from pydantic import Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.api.models.collection import (
    CollectionIdentificationChangeItemAPIRead, CollectionIdentificationProfileFilesAPIRead,
)
from backend.api.models.collection_contract import CollectionWordsAPIRead
from backend.api.models.source import NamesAPIRead
from backend.types.collection_types import EpisodeIdentifier


class MovedPartAPIRead(ResponseBase):
    """The videos of one list that move to another season of their collection."""

    label: str
    """What they are of, such as the list that holds them in their new season."""
    names: NamesAPIRead
    count: int
    to_season: str
    examples: list[str]
    """The titles of the videos, newest first, up to a few dozen."""
    files_moved: int = 0
    """Downloads whose files move along into their new season."""


class MovePreviewAPIRead(ResponseBase):
    """What the Move action does to the collection."""

    slug: str
    title: str
    type: str
    episode_identifier: EpisodeIdentifier
    parts: list[MovedPartAPIRead]
    renumber_offered: bool
    """Whether it can number its episodes again: not when it numbers them by date."""
    changes: list[CollectionIdentificationChangeItemAPIRead]
    """The episodes that get a new number when it numbers them again, newest first."""
    profiles: list[CollectionIdentificationProfileFilesAPIRead]
    """What numbering again does to each Local Media Profile's files; the metadata is rewritten either way."""
    files_follow: bool
    """Files moved, so its files are renamed and their metadata rewritten also when it keeps its numbers."""


class ReconcileAPIIn(RequestBase):
    """Move the Moved videos of a collection or one episode to the seasons they belong in now."""

    renumber: dict[str, bool] = Field(default_factory=dict, max_length=200)
    """By collection slug, whether the collection numbers its episodes again; left out, it does."""


class ReconcileAPIRead(ResponseBase):
    """Where the moved episode is now, for one episode's Move action."""

    episode_slug: Optional[str] = None
    collection_slug: Optional[str] = None


class MovesWaitingAPIRead(ResponseBase):
    """A collection whose videos wait for its Move action."""

    slug: str
    title: str
    moved: int
    words: CollectionWordsAPIRead
