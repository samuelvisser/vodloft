"""Putting videos where they belong now, files and all: the Reassigned ones, whose creator places them in another of
its collections, and the Moved ones, whose collection's lists put them in another season. Both wait for the user,
because moving renames their files; the Move action of a creator, a collection or one episode moves them.

It is the same move the creator's Edit page makes when a feed or list goes elsewhere: the same dialog says what
leaves and joins each collection, and the same follow-up numbers the episodes again, renames their files and rewrites
their metadata, as one operation of the creator when there is one.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Collection, Creator, Episode, EpisodeMediaDownload
from backend.services.episode_identification import collection_busy
from backend.services.errors import ServiceError
from backend.services.link_seasons import _holders, belongs_elsewhere, lists_in, moved_episodes, place_in_link_seasons
from backend.services.reassigned import (
    Reassignment, move_reassigned, reassigned_episodes, reassigned_in_creator, reassignment_of,
)
from backend.services.season_order import match_seasons_of_downloaded
from backend.services.section_moves import (
    _ON_DISK, Flow, SectionMovesPreview, _Moves, as_one_operation, follow_up, preview, snapshot,
)
from backend.services.creators import creator_words
from backend.services.sites import collection_words
from backend.types.collection_contracts import CollectionWords
from task_manager.scheduler.operations import spun_off_work


@dataclass(frozen=True)
class ReconcileScope:
    """What a Move action moves: every video of a creator, of one collection, or one video."""

    collections: list[Collection]
    """The collections whose videos move, and whose creator's other collections they may move to."""
    creator: Creator | None = None
    episode: Episode | None = None

    @classmethod
    def of_creator(cls, creator: Creator) -> "ReconcileScope":
        return cls(list(creator.collections), creator)

    @classmethod
    def of_collection(cls, collection: Collection) -> "ReconcileScope":
        return cls([collection], collection.creator)

    @classmethod
    def of_episode(cls, episode: Episode) -> "ReconcileScope":
        return cls([episode.collection], episode.collection.creator, episode)

    @property
    def involved(self) -> list[Collection]:
        """Every collection the videos may leave or join."""
        return list(self.creator.collections) if self.creator is not None else self.collections


def _reassigned(s: Session, scope: ReconcileScope) -> list[Reassignment]:
    if scope.episode is not None:
        item = reassignment_of(s, scope.episode)
        return [item] if item is not None else []
    if scope.creator is not None and len(scope.collections) > 1:
        return reassigned_in_creator(s, scope.creator)
    return [item for collection in scope.collections for item in reassigned_episodes(s, collection)]


def _moved(s: Session, scope: ReconcileScope, reassigned: set[int]) -> dict[int, list[Episode]]:
    """The videos to move to another season, by collection id: the ones that don't go to another collection."""
    if scope.episode is not None:
        episode = scope.episode
        if episode.id in reassigned or belongs_elsewhere(s, episode) is None:
            return {}
        return {episode.collection_id: [episode]}
    found = {}
    for collection in scope.collections:
        episodes = [episode for episode in moved_episodes(s, collection) if episode.id not in reassigned]
        if episodes:
            found[collection.id] = episodes
    return found


@dataclass(frozen=True)
class Waiting:
    """What a Move action would move: how many videos go to another collection, and how many to another season."""

    reassigned: int
    moved: int


def waiting(s: Session, scope: ReconcileScope) -> Waiting:
    """How many of the scope's videos wait to be moved. Reading only."""
    reassigned = _reassigned(s, scope)
    moved = _moved(s, scope, {item.episode.id for item in reassigned})
    return Waiting(len(reassigned), sum(len(episodes) for episodes in moved.values()))


@dataclass(frozen=True)
class WaitingIn:
    """A creator, or a collection of no creator, with videos that wait to be moved."""

    kind: str
    """creator or collection"""
    slug: str
    title: str
    waiting: Waiting
    words: CollectionWords
    """What it calls its seasons and episodes."""


def waiting_in_library(s: Session) -> list[WaitingIn]:
    """Every creator, and every collection without one, whose videos wait to be moved, by title. Reading only."""
    found = []
    for creator in s.scalars(select(Creator).order_by(Creator.title)):
        counts = waiting(s, ReconcileScope.of_creator(creator))
        if counts.reassigned or counts.moved:
            found.append(WaitingIn("creator", creator.slug, creator.title, counts, creator_words(creator)))
    for collection in s.scalars(select(Collection).where(Collection.creator_id.is_(None)).order_by(Collection.title)):
        counts = waiting(s, ReconcileScope.of_collection(collection))
        if counts.moved:
            found.append(WaitingIn("collection", collection.slug, collection.title, counts, collection_words(collection)))
    return found


def _holder_title(s: Session, collection: Collection, slug: str) -> str | None:
    holder = _holders(s, lists_in(collection)).get(slug)
    return holder.title if holder is not None else None


def _move_reassigned(s: Session, items: list[Reassignment], done: _Moves) -> None:
    groups: dict[tuple[int, int, str | None], list[int]] = {}
    for item in items:
        target = item.target.collection
        groups.setdefault(
            (item.episode.collection_id, target.id, _holder_title(s, target, item.target.source_slug)), [],
        ).append(item.episode.id)
    for (source_id, target_id, label), episode_ids in groups.items():
        target = s.get(Collection, target_id)
        names = collection_words(target).episode
        done.flows.append(Flow(None, names, source_id, target_id, episode_ids, label=label or names.plural))
        done.touched |= {source_id, target_id}
    done.result.merge(move_reassigned(s, items))


def _move_to_seasons(s: Session, collection: Collection, episodes: list[Episode], done: _Moves) -> None:
    ids = {episode.id for episode in episodes}
    names = collection_words(collection).episode
    labels = {episode.id: _holder_title(s, collection, episode.source_slug) for episode in episodes}
    before = {episode.id: episode.season_id for episode in episodes}
    place_in_link_seasons(s, collection, with_files=ids, drop=False)
    s.expire_all()
    moved = [episode_id for episode_id in sorted(ids) if s.get(Episode, episode_id).season_id != before[episode_id]]
    if not moved:
        return
    downloaded = set(s.scalars(
        select(EpisodeMediaDownload.media_item_id).where(
            EpisodeMediaDownload.media_item_id.in_(moved), EpisodeMediaDownload.artifact_status.in_(_ON_DISK),
        )
    ))
    collection = s.get(Collection, collection.id)
    if downloaded:
        # Their files move into their new season's folder, so they take its number.
        match_seasons_of_downloaded(s, collection, downloaded)
        done.result.rename.setdefault(collection.id, []).extend(sorted(downloaded))
    groups: dict[tuple[str, str | None], list[int]] = {}
    for episode_id in moved:
        episode = s.get(Episode, episode_id)
        groups.setdefault((episode.season.name, labels[episode_id]), []).append(episode_id)
    for (season, label), episode_ids in groups.items():
        done.flows.append(Flow(
            None, names, collection.id, collection.id, episode_ids, label=label or names.plural, to_season=season,
            files_moved=len(downloaded.intersection(episode_ids)),
        ))
    done.touched.add(collection.id)


def _apply(s: Session, scope: ReconcileScope) -> _Moves:
    reassigned = _reassigned(s, scope)
    moved = _moved(s, scope, {item.episode.id for item in reassigned})
    if not reassigned and not moved:
        raise ServiceError("Everything is where it belongs already", status_code=409)
    for collection in scope.involved:
        busy = collection_busy(s, collection, "moving its episodes")
        if busy is not None:
            raise ServiceError(busy)
    done = _Moves()
    if reassigned:
        _move_reassigned(s, reassigned, done)
    for collection_id, episodes in moved.items():
        _move_to_seasons(s, s.get(Collection, collection_id), episodes, done)
    return done


def preview_reconcile(s: Session, scope: ReconcileScope) -> SectionMovesPreview:
    """What the Move action does, collection by collection: the moves are made and rolled back.

    ``s`` is a write transaction's session; it is rolled back."""
    involved = scope.involved
    titles = {collection.id: (collection.slug, collection.title, collection.type) for collection in involved}
    before = snapshot(s, involved)
    return preview(s, titles, before, _apply(s, scope))


def reconcile(s: Session, scope: ReconcileScope, *, renumber: Mapping[str, bool]) -> None:
    """Move the videos to where they belong now, then number the videos of every collection that gained or lost some
    again, rename their files and rewrite their metadata. ``renumber`` says, by collection slug, which collections keep
    their numbers instead.

    ``s`` is a write transaction's session."""
    if scope.creator is None:
        follow_up(s, _apply(s, scope), renumber)
        return
    with spun_off_work(s) as work:
        done = _apply(s, scope)
        follow_up(s, done, renumber)
    collection = next(iter(scope.collections))
    as_one_operation(s, scope.creator, work, [], names=collection_words(collection).episode)


__all__ = ["ReconcileScope", "Waiting", "WaitingIn", "preview_reconcile", "reconcile", "waiting", "waiting_in_library"]
