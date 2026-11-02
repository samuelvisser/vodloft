"""The daily catalogue refresh, for collections whose Source has ``Feature.CATALOGUE_REFRESH``.

It runs after the daily re-scan and brings the episodes VODLoft already has up
to date: renamed videos, new thumbnails, and videos the Source no longer has.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Collection
from config.network import is_no_internet_error
from sources import Feature, get_source
from ...helpers.listed_collections import refresh_listed_collection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefreshResult:
    collections: int
    updated: int
    removed: int
    returned: int
    failed: tuple[str, ...]

    def summary(self) -> str:
        text = f"Refreshed {self.collections} {'collection' if self.collections == 1 else 'collections'}: {self.updated} episodes updated"
        if self.removed:
            text += f", {self.removed} no longer at the Source"
        if self.returned:
            text += f", {self.returned} back at the Source"
        return f"{text}; could not refresh {', '.join(self.failed)}" if self.failed else text

    def as_data(self) -> dict:
        return {
            "collections": self.collections, "updated": self.updated, "removed": self.removed,
            "returned": self.returned, "failed": list(self.failed),
        }


def run_catalogue_refresh(s: Session, *, collection_id: int | None = None) -> RefreshResult:
    """Refresh one collection, or every collection whose Source can refresh its items."""
    query = select(Collection).order_by(Collection.id)
    if collection_id is not None:
        query = query.where(Collection.id == collection_id)
    collections = [
        (collection.id, collection.title, get_source(collection.source_key)) for collection in s.scalars(query).all()
        if get_source(collection.source_key).has(Feature.CATALOGUE_REFRESH)
        and get_source(collection.source_key).has(Feature.EPISODE_LISTS)
    ]
    updated = removed = returned = 0
    failed: list[str] = []
    for collection_id_, title, source in collections:
        try:
            counts = refresh_listed_collection(s, collection_id=collection_id_, source=source)
        except Exception as exc:
            s.rollback()
            if is_no_internet_error(exc):
                raise
            logger.warning("Could not refresh %s: %s", title, exc)
            failed.append(title)
            continue
        updated, removed, returned = updated + counts.updated, removed + counts.removed, returned + counts.returned
    return RefreshResult(collections=len(collections), updated=updated, removed=removed, returned=returned, failed=tuple(failed))
