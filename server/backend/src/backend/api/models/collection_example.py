from __future__ import annotations

from pydantic import Field

from backend.api.models.base import RequestBase
from backend.services.example_episodes import ExampleCollection, ExampleSeason
from backend.types.collection_types import CollectionType, EpisodeIdentifier


class ExampleSeasonAPIIn(RequestBase):
    slug: str
    name: str


class ExampleCollectionAPIIn(RequestBase):
    """A collection the Add collection form describes before it is saved, whose newest episodes serve as examples."""

    source_key: str
    sharing_url: str
    slug: str
    title: str
    author_name: str = ""
    type: CollectionType
    episode_identifier: EpisodeIdentifier
    seasons: list[ExampleSeasonAPIIn] = Field(default_factory=list, max_length=500)

    def example(self) -> ExampleCollection:
        return ExampleCollection(
            source_key=self.source_key,
            url=self.sharing_url,
            slug=self.slug,
            title=self.title,
            author_name=self.author_name,
            type=CollectionType(self.type).value,
            episode_identifier=EpisodeIdentifier(self.episode_identifier),
            seasons=tuple(ExampleSeason(slug=season.slug, name=season.name) for season in self.seasons),
        )
