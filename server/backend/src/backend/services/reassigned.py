"""Reassigned: a video that the channel now places in another of its collections.

A channel keeps each of its creator's videos in one of its collections. A list, such as a playlist, beats a feed:
a video is in the collection whose lists hold it, which is the channel's own collection for the playlists that are its
seasons and a collection of its own for a playlist that is one. A video that a list of another collection holds, and
no list of its own collection, belongs there. One that is not downloaded simply moves: the collection it is in leaves
it, and a collection that does not hold it by a list does not add it. One with downloads stays where it is, files and
all, and is Reassigned until the user moves it.

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

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Channel, Collection, DownloadProfile, Episode, MediaDownloadBase
from backend.db.models.media_download import EpisodeMediaDownload
from backend.services.link_seasons import _holders, active_lists, link_seasons_on, remove_left_episode
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from sources import SectionKind


def _list_collection_ids(channel: Channel) -> set[int]:
    """The channel's collections of their own made from one of its lists."""
    urls = {section.url for section in channel.sections if section.kind == SectionKind.LIST}
    refs = {section.ref for section in channel.sections if section.kind == SectionKind.LIST}
    return {
        collection.id for collection in channel.collections
        if collection.id != channel.main_collection_id and (collection.sharing_url in urls or collection.slug in refs)
    }


@dataclass
class ChannelPlaces:
    """Which videos each of a channel's collections holds by a list, and which videos each one has."""

    order: list[Collection]
    held: dict[int, set[str]]
    """The slugs of the videos a list of the collection holds, by collection id."""
    episodes: dict[int, dict[str, Episode]] = field(default_factory=dict)
    """Each collection's whole videos, by slug, by collection id."""
    downloaded: set[int] = field(default_factory=set)
    """The ids of the episodes with a download, whether or not its file is there yet."""

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


def channel_places(s: Session, channel: Channel) -> ChannelPlaces:
    order = sorted(channel.collections, key=lambda collection: (collection.id != channel.main_collection_id, collection.id))
    lists = _list_collection_ids(channel)
    places = ChannelPlaces(order=order, held={})
    ids = [collection.id for collection in order]
    for collection in order:
        places.episodes[collection.id] = {}
    for episode in s.scalars(select(Episode).where(Episode.collection_id.in_(ids), Episode.part_of.is_(None))):
        places.episodes[episode.collection_id][episode.source_slug] = episode
    for collection in order:
        if collection.id == channel.main_collection_id:
            places.held[collection.id] = set(_holders(s, active_lists(s, collection))) if link_seasons_on(collection) else set()
        elif collection.id in lists:
            # Its own link is the list: every video it has that the list still lists.
            places.held[collection.id] = {
                slug for slug, episode in places.episodes[collection.id].items() if not episode.removed_from_source
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


def _reassigned(places: ChannelPlaces, collections: Iterable[Collection]) -> list[Reassignment]:
    found = []
    for collection in collections:
        for slug, episode in places.episodes.get(collection.id, {}).items():
            if episode.id not in places.downloaded:
                continue
            target = places.place(collection.id, slug)
            if target is not None:
                found.append(Reassignment(episode, places.episodes[target.id][slug]))
    return sorted(found, key=lambda item: item.episode.id)


def reassigned_episodes(s: Session, collection: Collection) -> list[Reassignment]:
    """The collection's downloaded videos that its channel places in another of its collections now."""
    if collection.channel is None:
        return []
    return _reassigned(channel_places(s, collection.channel), [collection])


def reassigned_in_channel(s: Session, channel: Channel) -> list[Reassignment]:
    places = channel_places(s, channel)
    return _reassigned(places, places.order)


def reassignment_of(s: Session, episode: Episode, *, downloaded: bool = True) -> Reassignment | None:
    """Where a downloaded video belongs now, when its channel places it in another collection. With ``downloaded``
    False also for a video without downloads, such as one whose old files were just removed."""
    channel = episode.collection.channel
    if channel is None or episode.part_of is not None:
        return None
    places = channel_places(s, channel)
    if downloaded and episode.id not in places.downloaded:
        return None
    target = places.place(episode.collection_id, episode.source_slug)
    return Reassignment(episode, places.episodes[target.id][episode.source_slug]) if target is not None else None


def placed_elsewhere(s: Session, collection: Collection) -> frozenset[str]:
    """The videos a collection does not add, because a list of another collection of its channel holds them. A
    collection made from a list adds every video of its list."""
    channel = collection.channel
    if channel is None or collection.id in _list_collection_ids(channel):
        return frozenset()
    return channel_places(s, channel).elsewhere(collection.id)


def settle_channel(s: Session, collection: Collection) -> int:
    """Let each of the channel's collections leave the videos that are not downloaded and that another collection
    holds by a list now. Returns how many left.

    ``s`` is a write transaction's session."""
    channel = collection.channel
    if channel is None:
        return 0
    places = channel_places(s, channel)
    leaving = [
        episode
        for other in places.order
        for slug, episode in places.episodes[other.id].items()
        if episode.id not in places.downloaded and places.place(other.id, slug) is not None
    ]
    for episode in leaving:
        remove_left_episode(s, episode)
    return len(leaving)


def awaiting_move(s: Session, collection: Collection) -> set[int]:
    """The ids of the collection's videos that are still downloaded in another collection of the channel, as
    Reassigned: its Download Profiles leave them until they are moved."""
    channel = collection.channel
    if channel is None:
        return set()
    places = channel_places(s, channel)
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

    channel = episode.collection.channel
    if channel is None or episode.part_of is not None:
        return
    places = channel_places(s, channel)
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
