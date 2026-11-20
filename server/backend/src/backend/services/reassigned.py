"""Reassigned: a video that the creator now places in another of its collections.

A creator keeps each of its videos in one of its collections. A list, such as a playlist, beats a feed:
a video is in the collection whose lists hold it, which is the creator's own collection for the playlists that are its
seasons and a collection of its own for a playlist that is one. A list of the creator that is not in a collection
keeps its videos out of it, also when a feed of that collection lists them: whether the list is a collection of its
own, was skipped or waits for the user's choice. Only a season of the collection itself lets such a video in. Each
collection of the creator lists those lists when it syncs, so it knows their videos before their own collections do.

A video that is not downloaded simply moves: the collection it is in leaves it, and a collection that does not hold it
by a list does not add it. One with downloads stays where it is, files and all. When another collection holds it by a
list, it is Reassigned until the user moves it there.

Moving a reassigned video hands each of its downloads to the same video in its new collection:

- A manual download stays manual, and its files are renamed to their new place.
- A download that one of the new collection's Download Profiles takes with the same Local Media Profile is renamed,
  and that profile, the first in the collection's order, keeps it.
- A download that none of them takes is renamed too, and becomes a manual download.
- A download that only Download Profiles with another Local Media Profile take is downloaded again in the new
  collection by the first of them. The old files are removed only once every download of the video in its new
  collection succeeded, so a failed download loses nothing.

Until it is moved, the new collection's Download Profiles leave the video alone, so it is not downloaded twice.
Reassigned is computed from the lists and the downloads, never stored.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.db.models import (
    Creator, CreatorSection, CreatorSectionItem, Collection, DownloadProfile, Episode, MediaDownloadBase,
)
from backend.db.models.media_download import EpisodeMediaDownload
from backend.services.link_seasons import _holders, active_lists, link_seasons_on, list_each, remove_left_episode
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from sources import ItemRef, SectionKind, Source


def _list_collection_ids(creator: Creator, seasons: frozenset[str] = frozenset()) -> set[int]:
    """The creator's collections of their own made from one of its lists. One whose list the creator placed in its
    own collection as a season, ``seasons``, is left over from before, and holds nothing any more."""
    lists = [section for section in creator.sections if section.kind == SectionKind.LIST and section.ref not in seasons]
    urls = {section.url for section in lists}
    refs = {section.ref for section in lists}
    return {
        collection.id for collection in creator.collections
        if collection.id not in creator.main_collection_ids and (collection.sharing_url in urls or collection.slug in refs)
    }


def _main_seasons(s: Session, creator: Creator) -> frozenset[str]:
    """The lists that are seasons of the creator's own collections, one for each account that has one."""
    return frozenset(
        link.ref for account in creator.accounts if account.main_collection is not None
        for link in active_lists(s, account.main_collection)
    )


@dataclass
class CreatorPlaces:
    """Which videos each of a creator's collections holds by a list, and which videos each one has.

    A creator can have thousands of videos, and only the few that are reassigned or leave are needed whole, so each
    video is known by its id here and loaded with ``episode``."""

    s: Session
    order: list[Collection]
    held: dict[int, set[str]]
    """The slugs of the videos a list of the collection holds, by collection id."""
    episodes: dict[int, dict[str, int]] = field(default_factory=dict)
    """The ids of each collection's whole videos, by slug, by collection id."""
    downloaded: set[int] = field(default_factory=set)
    """The ids of the episodes with a download, whether or not its file is there yet."""

    def episode(self, episode_id: int) -> Episode:
        return self.s.get(Episode, episode_id)

    def load(self, episode_ids: Iterable[int]) -> None:
        """Load the episodes at once, so that ``episode`` finds them without a query each."""
        ids = list(episode_ids)
        for start in range(0, len(ids), 500):
            list(self.s.scalars(select(Episode).where(Episode.id.in_(ids[start:start + 500]))))

    def place(self, collection_id: int, slug: str) -> Collection | None:
        """The collection the video belongs in, when that is another one than ``collection_id``."""
        if slug in self.held.get(collection_id, ()):
            return None
        return next((
            other for other in self.order
            if other.id != collection_id and slug in self.held[other.id] and slug in self.episodes[other.id]
        ), None)

    def elsewhere(self, collection_id: int) -> frozenset[str]:
        """The videos that another collection holds by a list, and this one does not."""
        here = self.held.get(collection_id, set())
        return frozenset(
            slug for other in self.order if other.id != collection_id for slug in self.held[other.id] if slug not in here
        )


def creator_places(s: Session, creator: Creator) -> CreatorPlaces:
    mains = creator.main_collection_ids
    order = sorted(creator.collections, key=lambda collection: (collection.id not in mains, collection.id))
    lists = _list_collection_ids(creator, _main_seasons(s, creator))
    places = CreatorPlaces(s=s, order=order, held={})
    ids = [collection.id for collection in order]
    for collection in order:
        places.episodes[collection.id] = {}
    gone: set[int] = set()
    for episode_id, collection_id, slug, removed in s.execute(
        select(Episode.id, Episode.collection_id, Episode.source_slug, Episode.removed_from_source)
        .where(Episode.collection_id.in_(ids), Episode.part_of.is_(None))
    ):
        places.episodes[collection_id][slug] = episode_id
        if removed:
            gone.add(episode_id)
    for collection in order:
        if collection.id in mains:
            places.held[collection.id] = set(_holders(s, active_lists(s, collection))) if link_seasons_on(collection) else set()
        elif collection.id in lists:
            # Its own link is the list: every video it has that the list still lists.
            places.held[collection.id] = {
                slug for slug, episode_id in places.episodes[collection.id].items() if episode_id not in gone
            }
        else:
            places.held[collection.id] = set()
    places.downloaded = set(s.scalars(
        select(MediaDownloadBase.media_item_id).join(Episode, Episode.id == MediaDownloadBase.media_item_id)
        .where(Episode.collection_id.in_(ids))
    ))
    return places


@dataclass(frozen=True)
class Reassignment:
    episode: Episode
    """The video where it is, with its downloads."""
    target: Episode
    """The same video in the collection it belongs in now."""


def _reassigned(places: CreatorPlaces, collections: Iterable[Collection]) -> list[Reassignment]:
    pairs = []
    for collection in collections:
        for slug, episode_id in places.episodes.get(collection.id, {}).items():
            if episode_id not in places.downloaded:
                continue
            target = places.place(collection.id, slug)
            if target is not None:
                pairs.append((episode_id, places.episodes[target.id][slug]))
    places.load(episode_id for pair in pairs for episode_id in pair)
    return [Reassignment(places.episode(episode_id), places.episode(target_id)) for episode_id, target_id in sorted(pairs)]


def reassigned_episodes(s: Session, collection: Collection) -> list[Reassignment]:
    """The collection's downloaded videos that its creator places in another of its collections now."""
    if collection.creator is None:
        return []
    return _reassigned(creator_places(s, collection.creator), [collection])


def reassigned_in_creator(s: Session, creator: Creator) -> list[Reassignment]:
    places = creator_places(s, creator)
    return _reassigned(places, places.order)


def reassignment_of(s: Session, episode: Episode, *, downloaded: bool = True) -> Reassignment | None:
    """Where a downloaded video belongs now, when its creator places it in another collection. With ``downloaded``
    False also for a video without downloads, such as one whose old files were just removed."""
    creator = episode.collection.creator
    if creator is None or episode.part_of is not None:
        return None
    places = creator_places(s, creator)
    if downloaded and episode.id not in places.downloaded:
        return None
    target = places.place(episode.collection_id, episode.source_slug)
    return Reassignment(episode, places.episode(places.episodes[target.id][episode.source_slug])) if target is not None else None


def placed_elsewhere(s: Session, collection: Collection) -> frozenset[str]:
    """The videos a collection does not add, because a list of another collection of its creator holds them, or a
    list of its creator that is not in it has them. A collection made from a list adds every video of its list."""
    creator = collection.creator
    if creator is None or collection.id in _list_collection_ids(creator, _main_seasons(s, creator)):
        return frozenset()
    return creator_places(s, creator).elsewhere(collection.id) | left_out(s, collection)


def lists_left_out(s: Session, collection: Collection) -> dict[int, str]:
    """The creator's lists on the collection's Source that are not in the collection, by the id of their section,
    with their links: the collection leaves out every video they have, also one its feeds list. Each list counts that
    is not one of the collection's seasons, whether it is a collection of its own, was skipped or waits for the
    user's choice. Empty for a collection made from a list, which adds every video of its list, and for one without a
    creator."""
    creator = collection.creator
    if creator is None or collection.id in _list_collection_ids(creator, _main_seasons(s, creator)):
        return {}
    seasons = {link.ref for link in active_lists(s, collection)}
    return {
        section.id: section.url for account in creator.accounts if account.source_key == collection.source_key
        for section in account.sections if section.kind == SectionKind.LIST and section.ref not in seasons
    }


def list_left_out(source: Source, lists: dict[int, str]) -> dict[int, tuple[ItemRef, ...]]:
    """The videos each of ``lists_left_out`` has now, by its section's id. A list that could not be listed is left
    out, and keeps the videos it had. Slow, so no transaction stays open."""
    return list_each(source, lists) if lists else {}


def save_left_out(s: Session, listed: dict[int, tuple[ItemRef, ...]]) -> None:
    """Store what the creator's lists have now.

    ``s`` is a write transaction's session."""
    known = set(s.scalars(select(CreatorSection.id).where(CreatorSection.id.in_(listed))))
    for section_id, items in listed.items():
        if section_id not in known:
            continue
        s.execute(delete(CreatorSectionItem).where(CreatorSectionItem.section_id == section_id))
        s.add_all(CreatorSectionItem(section_id=section_id, source_slug=slug) for slug in dict.fromkeys(item.slug for item in items))
    s.flush()


def left_out(s: Session, collection: Collection) -> frozenset[str]:
    """The videos the collection leaves out because a list of its creator that is not in it has them, unless one of
    its own seasons has them too."""
    lists = lists_left_out(s, collection)
    if not lists:
        return frozenset()
    slugs = set(s.scalars(select(CreatorSectionItem.source_slug).where(CreatorSectionItem.section_id.in_(lists))))
    return frozenset(slugs - set(_holders(s, active_lists(s, collection))))


def settle_creator(s: Session, collection: Collection) -> int:
    """Let each of the creator's collections leave the videos that are not downloaded and that another collection
    holds by a list now, or that a list of the creator that is not in it has. Returns how many left.

    ``s`` is a write transaction's session."""
    creator = collection.creator
    if creator is None:
        return 0
    places = creator_places(s, creator)
    outs = {other.id: left_out(s, other) for other in places.order}
    leaving = [
        episode_id
        for other in places.order
        for slug, episode_id in places.episodes[other.id].items()
        if episode_id not in places.downloaded and (places.place(other.id, slug) is not None or slug in outs[other.id])
    ]
    places.load(leaving)
    for episode_id in leaving:
        remove_left_episode(s, places.episode(episode_id))
    return len(leaving)


def awaiting_move(s: Session, collection: Collection) -> set[int]:
    """The ids of the collection's videos that are still downloaded in another collection of the creator, as
    Reassigned: its Download Profiles leave them until they are moved."""
    creator = collection.creator
    if creator is None:
        return set()
    places = creator_places(s, creator)
    waiting = {
        item.target.id for item in _reassigned(places, places.order) if item.target.collection_id == collection.id
    }
    return waiting - places.downloaded


def replaced_sources(s: Session, collection: Collection) -> list[Episode]:
    """The collection's reassigned videos whose downloads in their new collection all succeeded: their old files can
    go."""
    replaced = []
    for item in reassigned_episodes(s, collection):
        downloads = list(item.target.downloads)
        if downloads and all(
            download.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value for download in downloads
        ):
            replaced.append(item.episode)
    return replaced


@dataclass
class MoveResult:
    renamed: int = 0
    """Downloads whose files move to their new place."""
    downloading: int = 0
    """Downloads that the new collection makes again with its own Local Media Profile."""
    episodes: int = 0
    rename: dict[int, list[int]] = field(default_factory=dict)
    """The episodes to rename, by collection id."""
    sources: set[int] = field(default_factory=set)
    """The collections that keep a video until its new downloads succeed."""


def _taking_profiles(s: Session, target: Episode) -> list[DownloadProfile]:
    """The new collection's Download Profiles whose filters take the video, in the collection's order."""
    from backend.services.episode_filters import EpisodeSelection, wanted_episodes

    profiles = sorted(
        (profile for profile in target.collection.download_profiles if profile.enable_profile), key=lambda p: p.id,
    )
    return [
        profile for profile in profiles
        if wanted_episodes(s, EpisodeSelection.of_profile(profile), only_episode=target)
    ]


def _download_again(s: Session, target: Episode, profile: DownloadProfile) -> None:
    from backend.services.download_options import effective_filename_mode
    from backend.services.media_download_history import record_media_download_history
    from backend.types.media_download_history_types import MediaDownloadHistoryAction
    from backend.types.media_types import MediaType
    from backend.utils.output_template import resolve_episode_output_path

    local_media_profile = profile.local_media_profile
    download = EpisodeMediaDownload(
        type=MediaType.EPISODE.value, media_item_id=target.id, local_media_profile_id=local_media_profile.id,
        download_profile_id=profile.id, artifact_status=MediaDownloadArtifactStatus.ABSENT.value, file_path="",
    )
    s.add(download)
    s.flush()
    download.file_path = str(resolve_episode_output_path(
        local_media_profile.output_template, episode=target, local_media_profile=local_media_profile,
        media_download=download, filename_mode=effective_filename_mode(local_media_profile),
    ))
    s.flush()
    record_media_download_history(s, download.id, MediaDownloadHistoryAction.CREATED, metadata={
        "file_path": download.file_path, "local_media_profile_id": local_media_profile.id,
        "download_profile_id": profile.id,
    })


def move_reassigned(s: Session, items: Sequence[Reassignment]) -> MoveResult:
    """Hand each reassigned video's downloads to the same video in its new collection: renamed, or downloaded again
    there when the new collection downloads it with another Local Media Profile. A video that keeps no download goes.
    The caller renames the files of ``rename`` and lets the downloads of ``sources`` finish.

    ``s`` is a write transaction's session."""
    from task_manager.events.transactional import queue_event
    from task_manager.tasks.workers.download_profile_worker.event_adapter import DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT

    result = MoveResult()
    for item in items:
        episode, target = item.episode, item.target
        profiles: list[DownloadProfile] | None = None
        has = {download.local_media_profile_id for download in target.downloads}
        queued = False
        for download in list(episode.downloads):
            if download.local_media_profile_id in has:
                # The new collection has it already; the old one goes once that one is there.
                continue
            if download.download_profile_id is None:
                keeper = None
            else:
                profiles = _taking_profiles(s, target) if profiles is None else profiles
                same = [profile for profile in profiles if profile.local_media_profile_id == download.local_media_profile_id]
                if not same and profiles:
                    again = profiles[0]
                    if again.local_media_profile_id not in has:
                        _download_again(s, target, again)
                        has.add(again.local_media_profile_id)
                        result.downloading += 1
                        queued = True
                    continue
                keeper = same[0].id if same else None
            download.media_item_id = target.id
            download.download_profile_id = keeper
            s.flush()
            s.expire(download, ["media"])
            has.add(download.local_media_profile_id)
            result.renamed += 1
            result.rename.setdefault(target.collection_id, []).append(target.id)
        s.flush()
        s.expire(episode, ["downloads"])
        s.expire(target, ["downloads"])
        if queued:
            queue_event(s, DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT, {"resource_type": "episode", "resource_id": target.id})
        if episode.downloads:
            result.sources.add(episode.collection_id)
        else:
            remove_left_episode(s, episode)
        result.episodes += 1
    return result


def after_download(s: Session, episode: Episode) -> None:
    """A download of the video finished: when it is the new place of a reassigned video, its old files can go once
    every download here succeeded.

    ``s`` is a write transaction's session."""
    from task_manager.scheduler.transactional import queue_task_after_commit

    creator = episode.collection.creator
    if creator is None or episode.part_of is not None:
        return
    places = creator_places(s, creator)
    for collection_id in sorted({
        item.episode.collection_id for item in _reassigned(places, places.order) if item.target.id == episode.id
    }):
        queue_task_after_commit(s, def_key="remove_left_episodes", resource_type="collection", resource_id=collection_id)


def move_and_rename(s: Session, items: Sequence[Reassignment]) -> tuple[MoveResult, list[str]]:
    """Move the reassigned videos, rename their files into their new collections, and let the old files go once
    their new downloads succeed. Returns what moved, and the ids of the rename operations.

    ``s`` is a write transaction's session."""
    from backend.services.season_moves import queue_season_folder_moves
    from task_manager.scheduler.transactional import queue_task_after_commit

    result = move_reassigned(s, items)
    operations = []
    for collection_id, episode_ids in sorted(result.rename.items()):
        operation_id, _queued = queue_season_folder_moves(s, s.get(Collection, collection_id), sorted(set(episode_ids)))
        operations.append(operation_id)
    for collection_id in sorted(result.sources):
        queue_task_after_commit(s, def_key="remove_left_episodes", resource_type="collection", resource_id=collection_id)
    return result, operations
