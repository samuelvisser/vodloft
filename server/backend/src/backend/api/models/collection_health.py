from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field

from backend.api.models.base import ResponseBase
from backend.api.models.collection_contract import CollectionWordsAPIRead
from backend.types.collection_health_types import HealthIssueKind


class MovesIssueAPIRead(ResponseBase):
    """Downloads that the collection's season settings put in another season, which wait for its Move action."""

    kind: Literal[HealthIssueKind.MOVES] = HealthIssueKind.MOVES
    count: int
    seasons_plan: str
    """Why they move: what the collection's settings make its seasons now, in words."""


HealthIssueAPIRead = Annotated[Union[MovesIssueAPIRead], Field(discriminator="kind")]


class UnhealthyCollectionAPIRead(ResponseBase):
    """A collection that needs the user, with what for."""

    slug: str
    title: str
    words: CollectionWordsAPIRead
    """What it calls its seasons and episodes."""
    issues: list[HealthIssueAPIRead]
