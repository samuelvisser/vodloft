"""Moved: downloaded videos whose collection's lists put them in another season now. They wait for the user, because
moving renames their files; the Move action of a collection or of one episode moves them.

Afterwards the collection numbers its episodes again, unless the user said not to, renames their files and rewrites
their metadata. ``preview_reconcile`` plans the same moves and numbering on the planner's copy of the collection
without saving it, so what the dialog shows is what the Move action does.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Collection, Episode, EpisodeMediaDownload
from backend.services.episode_identification import (
    IdentificationChange, ProfileFilesChange, collection_busy, collection_work, profile_file_changes, queue_renumber, renumber_changes,
    renumbers,
)
from backend.services.errors import ServiceError
from backend.services.link_seasons import (
    belonging, holder_titles, moved, moved_episodes, place, seasons_plan,
)
from backend.services.collection_health import note_collection_health
from backend.services.season_state import SeasonsState, apply_state, load_state
from backend.services.move_causes import clear_move_causes, move_causes
from backend.services.season_order import match_downloaded
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


def _waiting(state: SeasonsState, scope: ReconcileScope) -> list[int]:
    """The ids of the scope's videos that wait to be moved, in the planner's copy of the collection."""
    if scope.episode is not None:
        return [scope.episode.id] if belonging(state, scope.episode.id) is not None else []
    return [episode.id for episode in moved(state)]


def waiting(s: Session, scope: ReconcileScope) -> int:
    """How many of the scope's videos wait to be moved. Reading only."""
    return len(_waiting(load_state(s, scope.collection), scope))


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


def _plan(s: Session, state: SeasonsState, scope: ReconcileScope) -> _Done:
    """Move the scope's videos where they belong in the planner's copy of the collection, as the Move action does,
    and say what moved where. Saves nothing."""
    collection = scope.collection
    ids = set(_waiting(state, scope))
    if not ids:
        raise ServiceError("Everything is where it belongs already", status_code=409)
    busy = collection_busy(s, collection, "moving its episodes")
    if busy is not None:
        raise ServiceError(busy)
    names = collection_words(collection).episode
    titles = holder_titles(state)
    labels = {episode_id: titles.get(state.episodes[episode_id].source_slug) for episode_id in ids}
    before = {episode_id: state.episodes[episode_id].season_id for episode_id in ids}
    place(state, with_files=ids, drop=False)
    done = _Done()
    moved_ids = [
        episode_id for episode_id in sorted(ids)
        if episode_id in state.episodes and state.episodes[episode_id].season_id != before[episode_id]
    ]
    if not moved_ids:
        return done
    downloaded = set(s.scalars(
        select(EpisodeMediaDownload.media_item_id).where(
            EpisodeMediaDownload.media_item_id.in_(moved_ids), EpisodeMediaDownload.artifact_status.in_(_ON_DISK),
        )
    ))
    if downloaded:
        # Their files move into their new season's folder, so they take its number.
        match_downloaded(state, downloaded)
        done.renamed = sorted(downloaded)
    grouped: dict[tuple[str, str | None], list[int]] = {}
    for episode_id in moved_ids:
        season = state.seasons[state.episodes[episode_id].season_id]
        grouped.setdefault((season.name, labels[episode_id]), []).append(episode_id)
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
    busy: str | None = None
    """What the move waits for, such as the listing a saved change started: what moves shows once it is done, as
    it may change what moves. Nothing else is planned meanwhile."""


def _newest_first(episodes: list[tuple[str, datetime | None]]) -> list[str]:
    earliest = datetime.min.replace(tzinfo=timezone.utc)
    return [title for title, _ in sorted(episodes, key=lambda item: item[1] or earliest, reverse=True)][:_EXAMPLES]


def preview_reconcile(s: Session, scope: ReconcileScope) -> MovePreview:
    """What the Move action does, as it plans the moves and the numbering after them on the planner's copy of the
    collection: nothing is saved. While VODLoft works on the collection, such as listing it again after a saved change,
    the preview says what it waits for instead. With nothing to move, it has no parts. Reading only."""
    collection = scope.collection
    identification = EpisodeIdentifier(collection.episode_identifier)
    offered = identification is not EpisodeIdentifier.DATE_BASED

    def nothing(busy: str | None = None) -> MovePreview:
        return MovePreview(
            slug=collection.slug, title=collection.title, type=collection.type, episode_identifier=identification,
            parts=[], causes=move_causes(collection), seasons_plan=seasons_plan(collection), renumber_offered=False,
            changes=[], profiles=[], files_follow=False, busy=busy,
        )

    work = collection_work(s, collection)
    if work is not None:
        return nothing(work.waiting())
    state = load_state(s, collection)
    if not _waiting(state, scope):
        # Such as when listing the collection again after a change put everything where it belongs.
        return nothing()
    done = _plan(s, state, scope)
    titles = {
        episode_id: (title, published) for episode_id, title, published in s.execute(
            select(Episode.id, Episode.title, Episode.published_date).where(Episode.collection_id == collection.id)
        )
    }
    parts = [
        MovedPart(
            label=group.label, names=group.names, count=len(group.episode_ids), to_season=group.to_season,
            examples=_newest_first([titles[episode_id] for episode_id in group.episode_ids if episode_id in titles]),
            files_moved=group.files_moved,
        )
        for group in done.groups
    ]
    changes, changed_ids = renumber_changes(s, state) if offered else ([], set())
    follow = bool(done.renamed)
    return MovePreview(
        slug=collection.slug, title=collection.title, type=collection.type, episode_identifier=identification,
        parts=parts, causes=move_causes(collection), seasons_plan=seasons_plan(collection),
        renumber_offered=offered and bool(changes), changes=changes,
        profiles=profile_file_changes(s, collection, changed_ids) if follow or changes else [], files_follow=follow,
    )


def reconcile(s: Session, scope: ReconcileScope, *, renumber: Mapping[str, bool]) -> None:
    """Move the videos to the seasons they belong in now, then number the collection's episodes again, rename their
    files and rewrite their metadata. ``renumber`` says, by collection slug, whether the collection keeps its numbers
    instead.

    ``s`` is a write transaction's session."""
    state = load_state(s, scope.collection)
    done = _plan(s, state, scope)
    apply_state(s, state)
    collection = s.get(Collection, scope.collection.id)
    note_collection_health(s, collection)
    if not moved_episodes(s, collection):
        clear_move_causes(collection)
    again = EpisodeIdentifier(collection.episode_identifier) is not EpisodeIdentifier.DATE_BASED and renumber.get(
        collection.slug, True,
    )
    if done.renamed or (again and renumbers(s, collection)):
        queue_renumber(s, collection, renumber=again)


__all__ = [
    "MovePreview", "ReconcileScope", "preview_reconcile", "reconcile", "waiting",
]
