"""Bulk edit in the Library: changing, syncing or deleting many Collections at once."""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.api.models.collection import CollectionAPIUpdate, CollectionBulkChangesIn
from backend.api.models.profile_bulk import BulkChangeIn, BulkResultRead, BulkSelectionIn, BulkSummaryRead
from backend.api.profile_bulk import in_order, offered_changes, reason_of, skipped, summarize
from backend.db.models import Collection
from backend.services.errors import ServiceError
from backend.services.sites import collection_site
from sources import Feature, get_source

from .service import delete_collection, request_collection_sync, update_collection

_FEATURES = {"split_chapters": Feature.CHAPTERS, "cookies_mode": Feature.OPTIONAL_COOKIES}
"""The settings only Collections of some Sources have, as their Edit page shows them."""


def _offers(collection: Collection, name: str) -> bool:
    feature = _FEATURES.get(name)
    return feature is None or get_source(collection.source_key).has(feature)


def _site_name(collection: Collection) -> str:
    return collection_site(collection).name


def _collections(s: Session, ids: list[int]) -> list[Collection]:
    return in_order(ids, s.query(Collection).filter(Collection.id.in_(ids)).all(), lambda item: item.id)


def summarize_collections(s: Session, body: BulkSelectionIn) -> BulkSummaryRead:
    return summarize(_collections(s, body.ids), CollectionBulkChangesIn, _offers, _site_name)


def change_collections(s: Session, body: BulkChangeIn[CollectionBulkChangesIn]) -> BulkResultRead:
    """Give the chosen Collections the same settings, saved as their Edit page saves them. One that cannot take
    them is skipped with why."""
    done = 0
    left = []
    for collection in _collections(s, body.ids):
        changes = offered_changes(body.changes, collection, _offers)
        if not changes:
            left.append(skipped(collection.id, collection.title, f"{_site_name(collection)} doesn't have these settings"))
            continue
        try:
            current = CollectionAPIUpdate.model_validate(collection)
            update_collection(s, collection.slug, CollectionAPIUpdate.model_validate({**current.model_dump(), **changes}))
        except (HTTPException, ServiceError, ValidationError) as error:
            left.append(skipped(collection.id, collection.title, reason_of(error)))
            continue
        done += 1
    return BulkResultRead(done=done, skipped=left)


def sync_collections(s: Session, body: BulkSelectionIn) -> BulkResultRead:
    """Look for new episodes of each chosen Collection now."""
    done = 0
    left = []
    for collection in _collections(s, body.ids):
        try:
            request_collection_sync(s, collection.slug)
        except (HTTPException, ServiceError) as error:
            left.append(skipped(collection.id, collection.title, reason_of(error)))
            continue
        done += 1
    return BulkResultRead(done=done, skipped=left)


def delete_collections(s: Session, body: BulkSelectionIn) -> BulkResultRead:
    collections = _collections(s, body.ids)
    for collection in collections:
        delete_collection(s, collection.slug)
    return BulkResultRead(done=len(collections), skipped=[])
