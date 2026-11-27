from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.api.models.collection_contract import CollectionWordsAPIRead
from backend.api.models.source import NamesAPIRead
from backend.types.collection_health_types import HealthIssueKind, HealthLevel


class MovesIssueAPIRead(ResponseBase):
    """Downloads that the collection's season settings put in another season, which wait for its Move action."""

    kind: Literal[HealthIssueKind.MOVES] = HealthIssueKind.MOVES
    level: HealthLevel
    count: int
    seasons_plan: str
    """Why they move: what the collection's settings make its seasons now, in words."""


class NewListsIssueAPIRead(ResponseBase):
    """Lists the collection's channel added later, which wait for the user's choice in its Seasons dialog."""

    kind: Literal[HealthIssueKind.NEW_LISTS] = HealthIssueKind.NEW_LISTS
    level: HealthLevel
    count: int
    names: NamesAPIRead
    """What the collection calls its lists, such as playlists."""


HealthIssueAPIRead = Annotated[Union[MovesIssueAPIRead, NewListsIssueAPIRead], Field(discriminator="kind")]


class UnhealthyCollectionAPIRead(ResponseBase):
    """A collection that needs the user, with what for."""

    slug: str
    title: str
    words: CollectionWordsAPIRead
    """What it calls its seasons and episodes."""
    issues: list[HealthIssueAPIRead]


class SuggestedCollectionAPIRead(ResponseBase):
    slug: str
    title: str


class CreatorSuggestionAPIRead(ResponseBase):
    """Several collections of one creator that are in no creator yet, which the user can group under the creator."""

    kind: Literal[HealthIssueKind.CREATORS] = HealthIssueKind.CREATORS
    level: HealthLevel
    site_key: str
    ref: str
    title: str
    """The creator's name."""
    creator_names: NamesAPIRead
    """What the Site calls its creators."""
    site_name: str
    collections: list[SuggestedCollectionAPIRead]
    creator_slug: str | None = None
    """The creator in the Library already, when they are: the collections join them."""
    creator_title: str | None = None


class LibraryHealthAPIRead(ResponseBase):
    """What the collection health check found that needs the user."""

    collections: list[UnhealthyCollectionAPIRead]
    creator_suggestions: list[CreatorSuggestionAPIRead]


class HealthCheckAPIRead(ResponseBase):
    kind: HealthIssueKind
    title: str
    """What it checks, in words."""
    on: bool


class HealthChecksAPIRead(ResponseBase):
    """The checks of the collection health check, and which are on."""

    checks: list[HealthCheckAPIRead]
    dismissed: int
    """How many suggestions the user dismissed for good, or put off for now."""


class HealthCheckAPIUpdate(RequestBase):
    on: bool


class SuggestionAnswerAPIIn(RequestBase):
    """What the user does with a suggestion: Later puts it off for a week, Dismiss for good."""

    answer: Literal["later", "dismiss"]
