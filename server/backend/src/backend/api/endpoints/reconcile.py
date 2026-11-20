"""The Move action of a creator, a collection and one episode: what it does, and doing it."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.models.creator import CreatorSectionMovesPreviewAPIRead, ReconcileAPIIn, ReconcileAPIRead
from backend.db.models import Collection, Creator, Episode
from backend.services.reassigned import reassignment_of
from backend.services.reconcile import ReconcileScope, preview_reconcile, reconcile

Scope = Callable[[Session], ReconcileScope]


def _found(s: Session, model, slug: str, what: str):
    found = s.scalar(select(model).where(model.slug == slug))
    if found is None:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return found


def creator_scope(slug: str) -> Scope:
    return lambda s: ReconcileScope.of_creator(_found(s, Creator, slug, "Creator"))


def collection_scope(slug: str) -> Scope:
    return lambda s: ReconcileScope.of_collection(_found(s, Collection, slug, "Collection"))


def episode_scope(slug: str) -> Scope:
    return lambda s: ReconcileScope.of_episode(_found(s, Episode, slug, "Episode"))


def preview_move(s: Session, scope: Scope) -> CreatorSectionMovesPreviewAPIRead:
    """What the Move action does to each collection. The moves are made and rolled back.

    ``s`` is a write transaction's session."""
    return CreatorSectionMovesPreviewAPIRead.model_validate(preview_reconcile(s, scope(s)))


def move(s: Session, scope: Scope, body: ReconcileAPIIn) -> ReconcileAPIRead:
    """Move the videos to where they belong now. For one episode, says where it is then.

    ``s`` is a write transaction's session."""
    found = scope(s)
    episode = found.episode
    target = reassignment_of(s, episode) if episode is not None else None
    reconcile(s, found, renumber=body.renumber)
    if episode is None:
        return ReconcileAPIRead()
    place = target.target if target is not None else episode
    return ReconcileAPIRead(episode_slug=place.slug, collection_slug=place.collection.slug)
