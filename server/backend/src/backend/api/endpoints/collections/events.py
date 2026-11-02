from __future__ import annotations

from backend.db.models import Collection


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
