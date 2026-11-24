"""Moved: downloaded videos whose collection's lists put them in another season now. They wait for the user, because
moving renames their files; the Move action of a collection or of one episode moves them.

Afterwards the collection numbers its episodes again, unless the user said not to, renames their files and rewrites
their metadata. ``preview_reconcile`` makes the same moves and rolls them back, so what the dialog shows is what the
Move action does.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Collection, Episode, EpisodeMediaDownload
from backend.services.episode_identification import (
    IdentificationChange, ProfileFilesChange, collection_busy, plan_identification, profile_file_changes,
    queue_renumber, renumber_changes,
)
from backend.services.errors import ServiceError
from backend.services.link_seasons import (
    _holders, belongs_elsewhere, lists_in, moved_episodes, place_in_link_seasons, seasons_plan,
)
from backend.services.move_causes import clear_move_causes, move_causes
from backend.services.season_order import match_seasons_of_downloaded
from backend.services.sites import collection_words
from backend.types.collection_contracts import CollectionWords
from backend.types.collection_types import EpisodeIdentifier
from backend.types.move_cause_types import MoveCause
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from sources import Names

_ON_DISK = (MediaDownloadArtifactStatus.AVAILABLE.value, MediaDownloadArtifactStatus.CORRUPTED.value)
# Episodes the dialog names of each group that moves.
_EXAMPLES = 50


@dataclass(frozen=True)
class ReconcileScope:
    """What a Move action moves: the Moved videos of one collection, or one video."""

    collection: Collection
    episode: Episode | None = None

    @classmethod
    def of_collection(cls, collection: Collection) -> "ReconcileScope":
        return cls(collection)

    @classmethod
    def of_episode(cls, episode: Episode) -> "ReconcileScope":
        return cls(episode.collection, episode)


def _moved(s: Session, scope: ReconcileScope) -> list[Episode]:
    if scope.episode is not None:
        return [scope.episode] if belongs_elsewhere(s, scope.episode) is not None else []
    return list(moved_episodes(s, scope.collection))


def waiting(s: Session, scope: ReconcileScope) -> int:
    """How many of the scope's videos wait to be moved. Reading only."""
    return len(_moved(s, scope))


@dataclass(frozen=True)
class _Group:
    """The videos that move to one season, from one list."""

    names: Names
    label: str
    to_season: str
    episode_ids: list[int]
    files_moved: int


@dataclass
class _Done:
    groups: list[_Group] = field(default_factory=list)
    renamed: list[int] = field(default_factory=list)
    """The episodes whose files move into their new season's folder."""


def _holder_title(s: Session, collection: Collection, slug: str) -> str | None:
    holder = _holders(s, lists_in(collection)).get(slug)
    return holder.title if holder is not None else None


def _apply(s: Session, scope: ReconcileScope) -> _Done:
    collection = scope.collection
    episodes = _moved(s, scope)
    if not episodes:
        raise ServiceError("Everything is where it belongs already", status_code=409)
    busy = collection_busy(s, collection, "moving its episodes")
    if busy is not None:
        raise ServiceError(busy)
    ids = {episode.id for episode in episodes}
    names = collection_words(collection).episode
    labels = {episode.id: _holder_title(s, collection, episode.source_slug) for episode in episodes}
    before = {episode.id: episode.season_id for episode in episodes}
    place_in_link_seasons(s, collection, with_files=ids, drop=False)
    s.expire_all()
    done = _Done()
    moved = [episode_id for episode_id in sorted(ids) if s.get(Episode, episode_id).season_id != before[episode_id]]
    if not moved:
        return done
    downloaded = set(s.scalars(
        select(EpisodeMediaDownload.media_item_id).where(
            EpisodeMediaDownload.media_item_id.in_(moved), EpisodeMediaDownload.artifact_status.in_(_ON_DISK),
        )
    ))
    collection = s.get(Collection, collection.id)
    if downloaded:
        # Their files move into their new season's folder, so they take its number.
        match_seasons_of_downloaded(s, collection, downloaded)
        done.renamed = sorted(downloaded)
    grouped: dict[tuple[str, str | None], list[int]] = {}
    for episode_id in moved:
        grouped.setdefault((s.get(Episode, episode_id).season.name, labels[episode_id]), []).append(episode_id)
    for (season, label), episode_ids in grouped.items():
        done.groups.append(_Group(
            names, label or names.plural, season, episode_ids, len(downloaded.intersection(episode_ids)),
        ))
    return done


@dataclass(frozen=True)
class MovedPart:
    """The videos of one list that move to another season of their collection."""

    label: str
    """What they are of, such as the list that holds them in their new season."""
    names: Names
    count: int
    to_season: str
    examples: list[str]
    """The titles of the videos, newest first, up to a few dozen."""
    files_moved: int = 0
    """Downloads whose files move along into their new season."""


@dataclass(frozen=True)
class MovePreview:
    """What the Move action does to the collection."""

    slug: str
    title: str
    type: str
    episode_identifier: EpisodeIdentifier
    parts: list[MovedPart]
    causes: list[MoveCause]
    """The setting changes that made them wait, each as it was and is now; none when VODLoft recorded none."""
    seasons_plan: str
    """What the collection's settings make its seasons now, in words: why they move when no change was recorded."""
    renumber_offered: bool
    """Whether it can number its episodes again: not when it numbers them by date."""
    changes: list[IdentificationChange]
    """The episodes that get a new number when it numbers them again, newest first."""
    profiles: list[ProfileFilesChange]
    """What numbering again does to each Local Media Profile's files; the metadata is rewritten either way."""
    files_follow: bool
    """Files moved, so its files are renamed and their metadata rewritten also when it keeps its numbers."""


def _newest_first(episodes: list[tuple[str, datetime | None]]) -> list[str]:
    earliest = datetime.min.replace(tzinfo=timezone.utc)
    return [title for title, _ in sorted(episodes, key=lambda item: item[1] or earliest, reverse=True)][:_EXAMPLES]


def preview_reconcile(s: Session, scope: ReconcileScope) -> MovePreview:
    """What the Move action does: the moves are made and rolled back.

    ``s`` is a write transaction's session; it is rolled back."""
    collection = scope.collection
    slug, title, type_ = collection.slug, collection.title, collection.type
    plan = seasons_plan(collection)
    causes = move_causes(collection)
    before = {
        episode.id: (episode.title, episode.published_date)
        for episode in s.scalars(select(Episode).where(Episode.collection_id == collection.id))
    }
    done = _apply(s, scope)
    s.flush()
    s.expire_all()
    collection = s.get(Collection, collection.id)
    parts = [
        MovedPart(
            label=group.label, names=group.names, count=len(group.episode_ids), to_season=group.to_season,
            examples=_newest_first([before[episode_id] for episode_id in group.episode_ids if episode_id in before]),
            files_moved=group.files_moved,
        )
        for group in done.groups
    ]
    identification = EpisodeIdentifier(collection.episode_identifier)
    offered = identification is not EpisodeIdentifier.DATE_BASED
    changes, changed_ids = renumber_changes(s, collection) if offered else ([], set())
    follow = bool(done.renamed)
    preview = MovePreview(
        slug=slug, title=title, type=type_, episode_identifier=identification, parts=parts, causes=causes, seasons_plan=plan,
        renumber_offered=offered and bool(changes), changes=changes,
        profiles=profile_file_changes(s, collection, changed_ids) if follow or changes else [], files_follow=follow,
    )
    s.rollback()
    return preview


def reconcile(s: Session, scope: ReconcileScope, *, renumber: Mapping[str, bool]) -> None:
    """Move the videos to the seasons they belong in now, then number the collection's episodes again, rename their
    files and rewrite their metadata. ``renumber`` says, by collection slug, whether the collection keeps its numbers
    instead.

    ``s`` is a write transaction's session."""
    done = _apply(s, scope)
    collection = s.get(Collection, scope.collection.id)
    if not moved_episodes(s, collection):
        clear_move_causes(collection)
    again = EpisodeIdentifier(collection.episode_identifier) is not EpisodeIdentifier.DATE_BASED and renumber.get(
        collection.slug, True,
    )
    if done.renamed or (again and plan_identification(
        s, collection, EpisodeIdentifier(collection.episode_identifier),
    ).identifiers):
        queue_renumber(s, collection, renumber=again)


__all__ = [
    "MovePreview", "ReconcileScope", "preview_reconcile", "reconcile", "waiting",
]
