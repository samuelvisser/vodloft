"""Adding a Collection to the Library, the same way wherever it comes from."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db.models import Collection
from backend.operations.collections import CollectionIndexOperation
from backend.services.errors import ServiceError
from backend.services.sites import place_collection
from backend.types.dailywire_user_info import DwMembershipLevel
from sources import Feature, UnknownSourceError, get_source
from task_manager.events.transactional import queue_event
from task_manager.scheduler.operation_factory import create_operation


class CollectionAdded(dict[str, object]):
    """Canonical payload for the ``collection.added`` domain event."""

    def __init__(self, collection: Collection) -> None:
        super().__init__(
            resource_id=collection.id,
            id=collection.id,
            slug=collection.slug,
            title=collection.title,
            initial_index=True,
        )


def add_collection(s: Session, collection: Collection, *, added_by_id: int | None = None) -> None:
    """Put a new Collection in the Library, on its Site; ``index_new_collection`` starts it once it is complete."""
    try:
        source = get_source(collection.source_key)
    except UnknownSourceError as exc:
        raise ServiceError(str(exc)) from exc
    if not source.has(Feature.COLLECTIONS):
        raise ServiceError(f"{source.name} has no shows")
    collection.added_by_id = added_by_id
    if source.has(Feature.EPISODE_LISTS):
        # Indexing puts the episodes in the Source's own seasons, or in a season per
        # upload year. Seasons given here are the Source's, picked for a Download
        # Profile; indexing matches them by slug and numbers them.
        collection.membership_level = DwMembershipLevel.FREE.value
    place_collection(s, collection)
    s.add(collection)


def index_new_collection(s: Session, collection: Collection) -> None:
    """Index a Collection that was just added, and tell everyone it is there."""
    s.flush()
    create_operation(s, CollectionIndexOperation(collection))
    queue_event(s, "collection.added", CollectionAdded(collection))
