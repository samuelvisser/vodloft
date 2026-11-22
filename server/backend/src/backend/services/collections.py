"""Adding a Collection to the Library, the same way wherever it comes from."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Collection
from backend.operations.collections import CollectionIndexOperation, CollectionSyncOperation
from backend.services.errors import ServiceError
from backend.services.sites import collection_kind, place_collection
from backend.types import work_weights
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from backend.types.dailywire_user_info import DwMembershipLevel
from backend.types.link_season_types import CollectionKind, LinkSeasons, OutsideVideos, RepeatVideos
from backend.utils.helpers import generate_uuid, slugify
from sources import Feature, UnknownSourceError, all_sources, get_source, source_site
from task_manager.events.transactional import queue_event
from task_manager.scheduler.operation_factory import create_operation
from task_manager.scheduler.operations import queue_operation_target_dispatch
from task_manager.scheduler.types import OperationSource


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
    _set_kind(collection)
    if source.has(Feature.EPISODE_LISTS):
        # Indexing puts the episodes in the Source's own seasons, or in a season per
        # upload year. Seasons given here are the Source's, picked for a Download
        # Profile; indexing matches them by slug and numbers them.
        collection.membership_level = DwMembershipLevel.FREE.value
    place_collection(s, collection)
    s.add(collection)


def _set_kind(collection: Collection) -> None:
    """Tell a new collection what its link is, and give a channel collection its Site's defaults where the request
    left them: the lists the user picks are seasons, or every list, new lists of the channel are added, the videos they
    have that the channel's feeds don't are added too, a video in several lists is in each where the Site says so, and
    the channel season holds what its Site's channels hold."""
    collection.kind = collection_kind(collection.sharing_url, collection.source_key).value
    if collection.kind != CollectionKind.CHANNEL.value:
        return
    site = source_site(collection.sharing_url, collection.source_key)
    if collection.channel_season is None:
        collection.channel_season = site.channel_season.value
    if site.link_seasons and collection.link_seasons is None:
        collection.link_seasons = (LinkSeasons.ALL if site.every_list_a_season else LinkSeasons.SELECTED).value
        if collection.outside_videos is None:
            collection.outside_videos = OutsideVideos.ADD.value
    if site.whole_lists and collection.repeat_videos is None:
        collection.repeat_videos = RepeatVideos.EACH_SEASON.value


def reindex_collection(s: Session, collection: Collection) -> None:
    """List a Collection again, as Sync now does, after its links changed. VODLoft starts it itself, so it runs in the
    background without a toast when it finishes."""
    s.flush()
    operation = create_operation(s, CollectionSyncOperation(collection, source=OperationSource.SYSTEM.value))
    queue_operation_target_dispatch(s, operation.id, operation.targets[0].slot_key)


def index_new_collection(s: Session, collection: Collection, *, expected_videos: int | None = None) -> None:
    """Index a Collection that was just added, and tell everyone it is there. ``expected_videos``, when known, is how
    many videos its link has, which weighs its indexing against the other parts of an action that added it."""
    s.flush()
    create_operation(s, CollectionIndexOperation(
        collection, work_weight=max(work_weights.DEFAULT, expected_videos * work_weights.LIST_VIDEO)
        if expected_videos else None,
    ))
    queue_event(s, "collection.added", CollectionAdded(collection))


def add_links_only_collection(
    s: Session, *, title: str, collection_type: CollectionType, added_by_id: int | None = None,
    episode_identifier: EpisodeIdentifier = EpisodeIdentifier.SEASONAL,
) -> Collection:
    """A new Collection without a link of its own, which holds only what the links the user gives it have: each one,
    such as a playlist, is one of its seasons. It is on no Site until it gets links, and can take them from any Site
    its Source fetches."""
    source = next((source for source in all_sources() if source.has(Feature.LINK_COLLECTIONS)), None)
    if source is None:
        raise ServiceError("VODLoft has no Source that can hold a collection of links", field="title")
    base = slugify(title) or "collection"
    slug, suffix = base, 2
    while s.scalar(select(Collection.id).where(Collection.slug == slug)) is not None:
        slug, suffix = f"{base}-{suffix}", suffix + 1
    collection = Collection(
        uuid=generate_uuid(), slug=slug, source_key=source.id, title=title.strip(), sharing_url=None,
        membership_level=DwMembershipLevel.FREE.value, type=collection_type.value,
        episode_identifier=episode_identifier.value, author_name="", author_slug="",
        link_seasons=LinkSeasons.ALL.value, outside_videos=OutsideVideos.ONLY.value,
    )
    add_collection(s, collection, added_by_id=added_by_id)
    s.flush()
    queue_event(s, "collection.added", CollectionAdded(collection))
    return collection
