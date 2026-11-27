"""Bulk edit in the Library: changing, syncing or deleting many Collections at once."""
from __future__ import annotations

from collections import Counter

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.api.models.collection import (
    CollectionAPIUpdate, CollectionBulkChangeIn, CollectionBulkChangesIn, CollectionBulkFeedRead,
    CollectionBulkSummaryRead,
)
from backend.api.models.collection_seasons import CollectionBulkReviewItemRead, CollectionBulkReviewRead, CollectionSeasonsAPIUpdate
from backend.api.models.profile_bulk import BulkFieldSummaryRead, BulkResultRead, BulkSelectionIn, BulkValueCountRead
from backend.api.profile_bulk import in_order, offered_changes, reason_of, skipped, summarize
from backend.db.models import Collection
from backend.services.errors import ServiceError
from backend.services.link_seasons import section_list_names
from backend.services.sites import collection_site
from backend.types.link_season_types import SourceRole
from sources import Feature, Names, get_source

from .seasons.service import (
    channel_feeds, feed_key, feed_roles, review_seasons, seasons_view, settings_with, takes_lists, update_seasons,
)
from .service import delete_collection, request_collection_sync, update_collection

_FEATURES = {"split_chapters": Feature.CHAPTERS, "cookies_mode": Feature.OPTIONAL_COOKIES}
"""The settings only Collections of some Sources have, as their Edit page shows them."""


_SEASONS = ("link_seasons", "feeds")
"""The settings of the Seasons dialog the bulk edit changes, which move downloads: the review shows what they do."""


def _offers(collection: Collection, name: str) -> bool:
    if name == "link_seasons":
        return takes_lists(collection)
    if name == "feeds":
        return bool(channel_feeds(collection))
    feature = _FEATURES.get(name)
    return feature is None or get_source(collection.source_key).has(feature)


def _seasons_changes(changes: CollectionBulkChangesIn, collection: Collection, renumber: bool = True) -> CollectionSeasonsAPIUpdate | None:
    """The Seasons dialog's settings the changes give the collection, or None when they change none of them."""
    if not changes.model_fields_set & set(_SEASONS):
        return None
    return settings_with(collection, changes.feeds or {}, changes.link_seasons, renumber=renumber)


def _site_name(collection: Collection) -> str:
    return collection_site(collection).name


def _collections(s: Session, ids: list[int]) -> list[Collection]:
    return in_order(ids, s.query(Collection).filter(Collection.id.in_(ids)).all(), lambda item: item.id)


def _feeds_summary(collections: list[Collection]) -> list[CollectionBulkFeedRead]:
    """Every feed of the chosen collections' channels, in the order their Sites list them, and what it is in each."""
    feeds: dict[str, tuple[object, str, Counter]] = {}
    for collection in collections:
        roles = feed_roles(collection)
        for feed in channel_feeds(collection):
            key = feed_key(collection, feed.feed_ref)
            feeds.setdefault(key, (feed.names, collection_site(collection).name, Counter()))[2][roles[key].value] += 1
    return [
        CollectionBulkFeedRead(
            key=key, names=names, site=site,
            summary=BulkFieldSummaryRead(
                offered=sum(counts.values()),
                values=[BulkValueCountRead(value=value, count=count) for value, count in counts.most_common()],
            ),
        )
        for key, (names, site, counts) in feeds.items()
    ]


def summarize_collections(s: Session, body: BulkSelectionIn) -> CollectionBulkSummaryRead:
    collections = _collections(s, body.ids)
    summary = summarize(collections, CollectionBulkChangesIn, _offers, _site_name, skip=("feeds",))
    # Whether a collection takes lists depends on what its link is, not only on its Site.
    summary.fields["linkSeasons"].sites_without = []
    lists = {}
    for collection in collections:
        if takes_lists(collection):
            names = section_list_names(collection)
            lists[names.plural] = names
    return CollectionBulkSummaryRead(
        count=summary.count, fields=summary.fields, feeds=_feeds_summary(collections),
        list_names=Names.joined(list(lists.values())) if lists else None,
    )


def change_collections(s: Session, body: CollectionBulkChangeIn) -> BulkResultRead:
    """Give the chosen Collections the same settings, saved as their Edit page and Seasons dialog save them, which
    moves their downloads as the review showed. One that cannot take them is skipped with why."""
    done = 0
    left = []
    for collection in _collections(s, body.ids):
        changes = offered_changes(body.changes, collection, _offers)
        if not changes:
            left.append(skipped(collection.id, collection.title, f"{_site_name(collection)} doesn't have these settings"))
            continue
        edit = {name: value for name, value in changes.items() if name not in _SEASONS}
        try:
            # One collection that cannot take the changes keeps all of its settings.
            with s.begin_nested():
                if edit:
                    current = CollectionAPIUpdate.model_validate(collection)
                    update_collection(s, collection.slug, CollectionAPIUpdate.model_validate({**current.model_dump(), **edit}))
                seasons = _seasons_changes(body.changes, collection, renumber=collection.id not in body.keep_numbers)
                if seasons is not None:
                    update_seasons(s, collection.slug, seasons)
        except (HTTPException, ServiceError, ValidationError) as error:
            left.append(skipped(collection.id, collection.title, reason_of(error)))
            continue
        done += 1
    return BulkResultRead(done=done, skipped=left)


def review_collections(s: Session, body: CollectionBulkChangeIn) -> CollectionBulkReviewRead:
    """What saving the changes does to the seasons of each chosen collection whose seasons they change, as the
    Seasons dialog's review shows it. A collection that cannot take them says why. Reading only."""
    reviews = []
    for collection in _collections(s, body.ids):
        try:
            seasons = _seasons_changes(body.changes, collection)
            if seasons is None:
                continue
            review = review_seasons(s, collection.slug, seasons)
        except (HTTPException, ServiceError, ValidationError) as error:
            reviews.append(CollectionBulkReviewItemRead(id=collection.id, title=collection.title, skipped=reason_of(error)))
            continue
        reviews.append(CollectionBulkReviewItemRead(
            id=collection.id, title=collection.title, view=seasons_view(s, collection.slug), review=review,
        ))
    return CollectionBulkReviewRead(collections=reviews)


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
