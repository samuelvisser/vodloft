"""The collection health check: VODLoft makes sure each collection is healthy by running every check below on it, every
night and whenever the user asks.

A collection stores its health itself (``Collection.healthy`` and ``health_issues``): what it needs the user for, by
the kind of issue, with how many things each concerns. VODLoft keeps that up to date as it works on a collection, such
as when it places its videos, so Home and the Library only read it. A check works out one kind of issue again from
what the collection holds and sets right what drifted. A new check is a ``HealthCheck`` added to ``CHECKS``, with a
kind of its own in ``HealthIssueKind`` and an issue that says what it found.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.db.core import write_when_changed
from backend.db.models import Collection
from backend.services.link_seasons import moved_episodes, seasons_plan
from backend.services.sites import collection_words
from backend.types.collection_contracts import CollectionWords
from backend.types.collection_health_types import HealthIssueKind


@dataclass(frozen=True)
class MovesIssue:
    """Downloads that the collection's season settings put in another season, which wait for its Move action."""

    count: int
    seasons_plan: str
    """Why they move: what the collection's settings make its seasons now, in words."""
    kind: HealthIssueKind = HealthIssueKind.MOVES


HealthIssue = MovesIssue
"""What one kind of issue tells the user. A union as more kinds are added."""


@dataclass(frozen=True)
class HealthCheck:
    kind: HealthIssueKind
    title: str
    """What it checks, in words, for the task's summary, such as downloads to move."""
    count: Callable[[Session, Collection], int]
    """How many things of this kind need the user, worked out from what the collection holds. Reading only."""
    issue: Callable[[Collection, int], HealthIssue]
    """What the issue tells the user, from the stored count."""


CHECKS: tuple[HealthCheck, ...] = (
    HealthCheck(
        HealthIssueKind.MOVES, "downloads to move",
        lambda s, collection: len(moved_episodes(s, collection)),
        lambda collection, count: MovesIssue(count, seasons_plan(collection)),
    ),
)
_BY_KIND = {check.kind.value: check for check in CHECKS}


@dataclass(frozen=True)
class CollectionHealth:
    """What the health check found on one collection, by the kinds of issue."""

    collection_id: int
    slug: str
    title: str
    needs_attention: list[str] = field(default_factory=list)
    corrected: list[str] = field(default_factory=list)
    """The kinds whose stored health was off, and is set right now."""

    @property
    def healthy(self) -> bool:
        return not self.needs_attention


def check_collection_health(collection_id: int) -> CollectionHealth | None:
    """Run every health check on the collection, and store its health. None when the collection is gone. Takes the
    writer's turn only when a check found the stored health off."""

    def work(s: Session) -> CollectionHealth | None:
        collection = s.get(Collection, collection_id)
        if collection is None:
            return None
        corrected = [check.kind.value for check in CHECKS if collection.note_health(check.kind, check.count(s, collection))]
        if corrected:
            # Setting right what VODLoft stored does not change the collection, so it keeps its last update time.
            flag_modified(collection, "updated_at")
        return CollectionHealth(collection.id, collection.slug, collection.title, sorted(collection.health_issues), corrected)

    return write_when_changed(work)


@dataclass(frozen=True)
class UnhealthyCollection:
    """A collection that needs the user, with what for."""

    slug: str
    title: str
    words: CollectionWords
    """What it calls its seasons and episodes."""
    issues: list[HealthIssue]


def unhealthy_collections(s: Session) -> list[UnhealthyCollection]:
    """Every collection that needs the user, by title, as it stored its health. Reading only."""
    return [
        UnhealthyCollection(collection.slug, collection.title, collection_words(collection), [
            _BY_KIND[kind].issue(collection, count) for kind, count in sorted(collection.health_issues.items())
            if kind in _BY_KIND
        ])
        for collection in s.scalars(select(Collection).where(Collection.healthy.is_(False)).order_by(Collection.title))
    ]


__all__ = [
    "CHECKS", "CollectionHealth", "HealthCheck", "HealthIssue", "MovesIssue", "UnhealthyCollection",
    "check_collection_health", "unhealthy_collections",
]
