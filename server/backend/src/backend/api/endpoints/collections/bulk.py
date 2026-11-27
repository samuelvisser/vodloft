"""Bulk edit in the Library: changing, syncing or deleting many Collections at once."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

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
from backend.services.list_previews import saving_plan
from backend.services.replaced_work import ReplacedWork, stop_replaced_work
from backend.db.core import get_session
from backend.services.sites import collection_site
from backend.types.collection_contracts import collection_contract
from backend.types.link_season_types import LooseVideos, SourceRole
from sources import Feature, Names, get_source

from .seasons.service import (
    channel_feeds, feed_key, feed_roles, review_seasons, saving_steps, seasons_view, settings_with, takes_lists,
    update_seasons,
)
from .service import delete_collection, request_collection_sync, update_collection

_FEATURES = {"split_chapters": Feature.CHAPTERS, "cookies_mode": Feature.OPTIONAL_COOKIES}
"""The settings only Collections of some Sources have, as their Edit page shows them."""


_SEASONS = ("link_seasons", "feeds", "loose_videos")
"""The settings of the Seasons dialog the bulk edit changes, which move downloads: the review shows what they do."""


def _offers(collection: Collection, name: str) -> bool:
    if name == "link_seasons":
        return takes_lists(collection)
    if name == "feeds":
        return bool(channel_feeds(collection))
    if name == "loose_videos":
        return _groups_videos(collection)
    feature = _FEATURES.get(name)
    return feature is None or get_source(collection.source_key).has(feature)


def _seasons_changes(changes: CollectionBulkChangesIn, collection: Collection, renumber: bool = True) -> CollectionSeasonsAPIUpdate | None:
    """The Seasons dialog's settings the changes give the collection, or None when they change none of them."""
    if not changes.model_fields_set & set(_SEASONS):
        return None
    return settings_with(
        collection, changes.feeds or {}, changes.link_seasons, renumber=renumber,
        loose_videos=changes.loose_videos if _groups_videos(collection) else None,
    )


def _groups_videos(collection: Collection) -> bool:
    """The collection groups what is part of it in one season or a season per year: a collection whose Source lists
    its videos, rather than one whose Source always has seasons of its own, as one whose episodes VODLoft looks up
    one by one does."""
    source = get_source(collection.source_key)
    return source.has(Feature.EPISODE_LISTS) and not source.has(Feature.EPISODE_LOOKUPS)


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
    summary = summarize(collections, CollectionBulkChangesIn, _offers, _site_name, skip=("feeds", "loose_videos"))
    # Whether a collection takes lists depends on what its link is, not only on its Site.
    summary.fields["linkSeasons"].sites_without = []
    lists = {}
    for collection in collections:
        if takes_lists(collection):
            names = section_list_names(collection)
            lists[names.plural] = names
    grouping = [collection for collection in collections if _groups_videos(collection)]
    # One season that also holds what has a season of its own is one season too.
    groupings = Counter(
        LooseVideos.BY_YEAR.value if collection.loose_videos == LooseVideos.BY_YEAR.value else LooseVideos.ONE_SEASON.value
        for collection in grouping
    )
    seasons = {}
    for collection in grouping:
        # VODLoft's own seasons, in the collection type's word, as the Seasons dialog names them.
        words = collection_contract(collection.type).words.season
        seasons[words.plural] = words
    return CollectionBulkSummaryRead(
        count=summary.count, fields=summary.fields, feeds=_feeds_summary(collections),
        list_names=Names.joined(list(lists.values())) if lists else None,
        loose_videos=BulkFieldSummaryRead(
            offered=len(grouping),
            values=[BulkValueCountRead(value=value, count=count) for value, count in groupings.most_common()],
        ) if grouping else None,
        season_names=Names.joined(list(seasons.values())) if seasons else None,
    )


def stop_replaced(body: CollectionBulkChangeIn) -> dict[int, ReplacedWork]:
    """Stop the work saving replaces on each chosen collection whose seasons the changes change, as saving its Seasons
    dialog does, and say what that work was still going to do, by collection. Not in a write transaction."""
    s = get_session()
    try:
        changing = [
            (collection.id, collection.slug) for collection in _collections(s, body.ids)
            if _offers_seasons(body.changes, collection)
        ]
    finally:
        s.rollback()
        s.close()
    return {collection_id: stop_replaced_work(slug) for collection_id, slug in changing}


def _offers_seasons(changes: CollectionBulkChangesIn, collection: Collection) -> bool:
    try:
        return _seasons_changes(changes, collection) is not None
    except (ServiceError, ValidationError):
        return False


def change_collections(
    s: Session, body: CollectionBulkChangeIn, replaced: Mapping[int, ReplacedWork] | None = None,
) -> BulkResultRead:
    """Give the chosen Collections the same settings, saved as their Edit page and Seasons dialog save them, which
    moves their downloads as the review showed. One that cannot take them is skipped with why. ``replaced`` is what
    the work ``stop_replaced`` stopped was still going to do."""
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
                    plan = saving_plan(collection.slug, body.saving_token, saving_steps(s, collection.slug, seasons))
                    update_seasons(s, collection.slug, seasons, plan=plan, replaced=(replaced or {}).get(collection.id, ReplacedWork()))
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
            reviews.append(CollectionBulkReviewItemRead(id=collection.id, slug=collection.slug, title=collection.title, skipped=reason_of(error)))
            continue
        reviews.append(CollectionBulkReviewItemRead(
            id=collection.id, slug=collection.slug, title=collection.title, view=seasons_view(s, collection.slug), review=review,
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
