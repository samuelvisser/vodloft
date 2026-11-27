"""Adding a Collection to the Library, the same way wherever it comes from."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.db.mixins.HasTaskResourcesMixin import delete_task_rows
from backend.db.models import Collection, CollectionLocalAsset, Episode, MediaDownloadBase, MediaItemBase, Metadata
from backend.operations.collections import CollectionIndexOperation, CollectionSyncOperation
from backend.services.errors import ServiceError
from backend.services.sites import collection_kind, place_collection
from backend.types import work_weights
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from backend.types.dailywire_user_info import DwMembershipLevel
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.link_season_types import ChannelSeason, CollectionKind, LinkSeasons, LooseVideos, OutsideVideos, RepeatVideos
from backend.utils.helpers import generate_uuid, slugify
from sources import Feature, SectionKind, UnknownSourceError, all_sources, get_source, source_site
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
    set_kind(collection)
    if source.has(Feature.EPISODE_LISTS):
        # Indexing puts the episodes in the Source's own seasons, or in a season per
        # upload year. Seasons given here are the Source's, picked for a Download
        # Profile; indexing matches them by slug and numbers them.
        collection.membership_level = DwMembershipLevel.FREE.value
    place_collection(s, collection)
    s.add(collection)


def set_kind(collection: Collection) -> None:
    """Tell a new collection what its link is, and give a channel collection its Site's defaults where the request
    left them: its lists are on, each new list of the channel is added as its kind says, the videos
    they have that the channel's feeds don't are added too, a video in several lists is in each where the Site says
    so, and the channel season holds what its Site's channels hold. A type that takes only albums, such as Music,
    starts with only the kinds of list that are albums, where its Site tells them apart."""
    collection.kind = collection_kind(collection.sharing_url, collection.source_key).value
    if collection.kind != CollectionKind.CHANNEL.value:
        _check_list_type(collection)
        return
    collection.list_type = None
    site = source_site(collection.sharing_url, collection.source_key)
    # The defaults are about the channel's lists, which only a Site whose lists can be seasons has.
    if not site.link_seasons:
        return
    if collection.loose_videos is None:
        # The channel season holds what its Site's channels hold: the whole channel, or what is in no list.
        whole = site.channel_season == ChannelSeason.EVERYTHING
        collection.loose_videos = (LooseVideos.EVERYTHING if whole else LooseVideos.ONE_SEASON).value
    if collection.link_seasons is None:
        collection.link_seasons = LinkSeasons.ON.value
        if collection.outside_videos is None:
            collection.outside_videos = OutsideVideos.ADD.value
    if site.whole_lists and collection.repeat_videos is None:
        collection.repeat_videos = RepeatVideos.EACH_SEASON.value


def _check_list_type(collection: Collection) -> None:
    """A collection of one list names the type of list its link is only by one its Site has."""
    if collection.list_type is None:
        return
    if collection.sharing_url is None:
        collection.list_type = None
        return
    site = source_site(collection.sharing_url, collection.source_key)
    if collection.list_type not in {type_.key for type_ in site.types_of(SectionKind.LIST)}:
        raise ServiceError(f"{site.name} has no type of list {collection.list_type!r}", field="list_type")


def reindex_collection(s: Session, collection: Collection, *, by_user: bool = False) -> None:
    """List a Collection again, as Sync now does, after its links changed. VODLoft starts it itself, so it runs in the
    background without a toast when it finishes. ``by_user`` says the user's change asked for it: the downloaded
    videos that leave then go with their files, as the user was told when saving."""
    s.flush()
    operation = create_operation(s, CollectionSyncOperation(collection, source=OperationSource.SYSTEM.value, by_user=by_user))
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
        link_seasons=LinkSeasons.ON.value, outside_videos=OutsideVideos.ONLY.value,
    )
    add_collection(s, collection, added_by_id=added_by_id)
    s.flush()
    queue_event(s, "collection.added", CollectionAdded(collection))
    return collection


def downloaded_files_of(s: Session, collection: Collection) -> list[tuple[str, tuple[str, ...]]]:
    """The files on disk of the collection's downloads: each media file, with the files VODLoft wrote beside it, such
    as subtitles and thumbnails, and the collection's own artwork and NFO files."""
    episodes = select(Episode.id).where(Episode.collection_id == collection.id).scalar_subquery()
    downloads = s.scalars(select(MediaDownloadBase).where(
        MediaDownloadBase.media_item_id.in_(episodes),
        MediaDownloadBase.artifact_status != MediaDownloadArtifactStatus.ABSENT.value,
    )).all()
    own = s.scalars(select(CollectionLocalAsset.file_path).where(CollectionLocalAsset.collection_id == collection.id))
    return [
        *((download.file_path, tuple(asset.path for asset in download.assets)) for download in downloads if download.file_path),
        *((path, ()) for path in own),
    ]


def remove_downloaded_files(files: list[tuple[str, tuple[str, ...]]]) -> None:
    """Delete these downloaded files, such as those of a collection that was just deleted, and the folders they
    leave empty. Runs after the transaction that forgot them."""
    from backend.services.download_relocation import remove_folders_left_empty
    from downloader.storage.artifacts import remove_download_artifacts

    folders: set[Path] = set()
    for path, sidecars in files:
        remove_download_artifacts(path, sidecar_paths=sidecars)
        folders.add(Path(path).parent)
        folders.update(Path(sidecar).parent for sidecar in sidecars)
    remove_folders_left_empty(folders)


def delete_episodes_of(s: Session, collection: Collection) -> None:
    """Delete every episode of the collection with its downloads, a few statements for the whole collection.

    Deleting the collection on its own would load each episode and each of its downloads to delete them one by
    one, which takes many seconds for a channel with thousands of videos. The files on disk stay.
    """
    episode_ids = set(s.scalars(select(Episode.id).where(Episode.collection_id == collection.id)))
    if not episode_ids:
        return
    episodes = select(Episode.id).where(Episode.collection_id == collection.id).scalar_subquery()
    download_ids = set(s.scalars(select(MediaDownloadBase.id).where(MediaDownloadBase.media_item_id.in_(episodes))))
    delete_task_rows(s, {"episode": episode_ids, "media_download": download_ids})

    downloads = select(MediaDownloadBase.id).where(MediaDownloadBase.media_item_id.in_(episodes)).scalar_subquery()
    for statement in (
        delete(Metadata).where(Metadata.parent_table == MediaDownloadBase.__metadata_parent_table__,
                               Metadata.parent_id.in_(downloads)),
        delete(Metadata).where(Metadata.parent_table == Episode.__tablename__, Metadata.parent_id.in_(episodes)),
        # Each download's own rows, its assets and its history follow through their foreign keys.
        delete(MediaDownloadBase).where(MediaDownloadBase.media_item_id.in_(episodes)),
        # The episode rows follow their media items through their foreign key.
        delete(MediaItemBase).where(MediaItemBase.id.in_(episodes)),
    ):
        s.execute(statement, execution_options={"synchronize_session": False})
    s.expire(collection, ["episodes", "seasons"])
