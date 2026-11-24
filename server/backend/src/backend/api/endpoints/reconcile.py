"""The Move action of a collection and of one episode: what it does, and doing it."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.models.reconcile import MovePreviewAPIRead, ReconcileAPIIn, ReconcileAPIRead
from backend.db.models import Collection, Episode
from backend.services.reconcile import ReconcileScope, preview_reconcile, reconcile

Scope = Callable[[Session], ReconcileScope]


def _found(s: Session, model, slug: str, what: str):
    found = s.scalar(select(model).where(model.slug == slug))
    if found is None:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return found


def collection_scope(slug: str) -> Scope:
    return lambda s: ReconcileScope.of_collection(_found(s, Collection, slug, "Collection"))


def episode_scope(slug: str) -> Scope:
    return lambda s: ReconcileScope.of_episode(_found(s, Episode, slug, "Episode"))


def preview_move(s: Session, scope: Scope) -> MovePreviewAPIRead:
    """What the Move action does to the collection. The moves are made and rolled back.

    ``s`` is a write transaction's session."""
    return MovePreviewAPIRead.model_validate(preview_reconcile(s, scope(s)))


def move(s: Session, scope: Scope, body: ReconcileAPIIn) -> ReconcileAPIRead:
    """Move the videos to the seasons they belong in now. For one episode, says where it is then.

    ``s`` is a write transaction's session."""
    found = scope(s)
    episode = found.episode
    reconcile(s, found, renumber=body.renumber)
    if episode is None:
        return ReconcileAPIRead()
    return ReconcileAPIRead(episode_slug=episode.slug, collection_slug=episode.collection.slug)
