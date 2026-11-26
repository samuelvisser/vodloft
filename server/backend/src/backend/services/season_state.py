"""A collection's seasons as the season planner works on them: a copy in memory of its seasons, its lists with what
they list, its episodes and the settings that place them. The planner (``link_seasons`` and ``season_order``) changes
the copy only, so the Seasons dialog can show what saving would do without saving anything, and saving writes the same
result: ``apply_state`` makes the database what the copy has become.

A season, list or episode the planner makes gets an id below zero until it is saved."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Collection, CollectionList, CollectionListItem, Episode, MediaDownloadBase, Season

# The collection's settings the planner reads, which the Seasons dialog changes in the copy before planning.
SETTINGS = (
    "link_seasons", "outside_videos", "feeds", "feed_seasons", "loose_videos", "repeat_videos", "custom_season_order",
    "new_lists", "episode_identifier",
)


@dataclass(eq=False)
class SeasonDraft:
    id: int
    collection_id: int
    slug: str
    name: str
    season_number: int
    index: int
    season_type: str
    origin: str
    loose: bool
    created_at: datetime | None


@dataclass(eq=False)
class ListDraft:
    """One of the collection's lists, with the slugs of what it lists, in its order."""

    record: CollectionList = field(repr=False)
    id: int
    title: str
    enabled: bool
    status: str
    as_season: bool
    is_default: bool
    added_by_user: bool
    site_position: int
    season_id: int | None
    items: tuple[str, ...] = ()

    def __getattr__(self, name):
        # What the planner never changes, such as the list's link, is the list's own.
        if name == "record":
            raise AttributeError(name)
        return getattr(self.record, name)


_LIST_FIELDS = ("enabled", "status", "as_season", "is_default", "season_id")


@dataclass(eq=False)
class EpisodeDraft:
    id: int
    slug: str
    source_slug: str
    part_of: str | None
    season_id: int
    from_link_season: bool
    episode_identifier: str | None
    published_date: datetime | None
    index: int
    removed_from_source: bool
    has_files: bool
    went_live_date: datetime | None = None
    scheduled_date: datetime | None = None
    created_at: datetime | None = None
    source_number: str | None = None
    """The Source's own episode number, such as The Daily Wire's, which its numbering follows."""
    copy_of: int | None = None
    """For an episode the planner makes of a video in another season: the episode it copies."""
    record: Episode | None = field(default=None, repr=False)
    """For a new video's episode that is not saved yet: the episode to save."""

    @property
    def video_slug(self) -> str:
        return self.part_of or self.source_slug


_EPISODE_FIELDS = ("season_id", "episode_identifier", "from_link_season", "removed_from_source")


class CollectionDraft:
    """The collection as the planner sees it: its settings and its lists and seasons as they are in the copy, and
    everything else as the collection has it."""

    def __init__(self, record: Collection, state: "SeasonsState"):
        self.__dict__["_record"] = record
        self.__dict__["_state"] = state
        for name in SETTINGS:
            value = getattr(record, name)
            self.__dict__[name] = dict(value) if isinstance(value, dict) else list(value) if isinstance(value, list) else value

    @property
    def lists(self) -> list[ListDraft]:
        return self._state.lists

    @property
    def seasons(self) -> list[SeasonDraft]:
        return list(self._state.seasons.values())

    def __getattr__(self, name):
        return getattr(self._record, name)

    def __setattr__(self, name, value):
        if name not in SETTINGS:
            raise AttributeError(f"The planner does not change the collection's {name}")
        self.__dict__[name] = value

    def keep_a_default_link(self, links: Iterable[ListDraft] | None = None) -> None:
        Collection.keep_a_default_link(self, links)


@dataclass
class Leaving:
    """An episode with files that leaves the collection: a task removes it with its files, unless the Home page asks
    whether to keep them first."""

    episode: EpisodeDraft
    by_user: bool
    """The user's own change made it leave, so its files go with it."""


class SeasonsState:
    """The copy of one collection's seasons, lists and episodes that the planner changes."""

    def __init__(self, s: Session, record: Collection, now: datetime | None = None):
        self.record = record
        self.now = now or datetime.now(timezone.utc)
        self._next = 0
        self.seasons: dict[int, SeasonDraft] = {}
        for season in sorted(record.seasons, key=lambda season: season.index):
            self.seasons[season.id] = SeasonDraft(
                id=season.id, collection_id=season.collection_id, slug=season.slug, name=season.name,
                season_number=season.season_number, index=season.index, season_type=season.season_type,
                origin=season.origin, loose=season.loose, created_at=season.created_at,
            )
        items: dict[int, list[str]] = {}
        ids = [playlist.id for playlist in record.lists]
        if ids:
            for list_id, slug in s.execute(
                select(CollectionListItem.list_id, CollectionListItem.source_slug)
                .where(CollectionListItem.list_id.in_(ids)).order_by(CollectionListItem.list_id, CollectionListItem.position)
            ):
                items.setdefault(list_id, []).append(slug)
        self.lists: list[ListDraft] = [
            ListDraft(
                record=playlist, id=playlist.id, title=playlist.title, enabled=playlist.enabled, status=playlist.status,
                as_season=playlist.as_season, is_default=playlist.is_default, added_by_user=playlist.added_by_user,
                site_position=playlist.site_position, season_id=playlist.season_id, items=tuple(items.get(playlist.id, ())),
            )
            for playlist in record.lists
        ]
        with_files = set(s.scalars(
            select(MediaDownloadBase.media_item_id).join(Episode, Episode.id == MediaDownloadBase.media_item_id)
            .where(Episode.collection_id == record.id)
        ))
        self.episodes: dict[int, EpisodeDraft] = {
            row.id: EpisodeDraft(
                id=row.id, slug=row.slug, source_slug=row.source_slug, part_of=row.part_of, season_id=row.season_id,
                from_link_season=row.from_link_season, episode_identifier=row.episode_identifier,
                published_date=row.published_date, index=row.index, removed_from_source=row.removed_from_source,
                has_files=row.id in with_files, went_live_date=row.went_live_date, scheduled_date=row.scheduled_date,
                created_at=row.created_at, source_number=row.source_number,
            )
            for row in s.execute(
                select(
                    Episode.id, Episode.slug, Episode.source_slug, Episode.part_of, Episode.season_id,
                    Episode.from_link_season, Episode.episode_identifier, Episode.published_date, Episode.index,
                    Episode.removed_from_source, Episode.went_live_date, Episode.scheduled_date, Episode.created_at,
                    Episode.source_number,
                ).where(Episode.collection_id == record.id).order_by(Episode.id)
            )
        }
        self.collection = CollectionDraft(record, self)
        self.gone: dict[int, EpisodeDraft] = {}
        """The episodes that leave the collection now, by id."""
        self.leaving: dict[int, Leaving] = {}
        """The episodes with files that leave once their files are removed, by id."""
        self.gone_seasons: set[int] = set()
        self.gone_lists: set[int] = set()
        self.made: set[int] = set()
        """The seasons the planner made, which a collection in the user's own order slots in by date."""
        self.files_memo: dict | None = None
        """What an open Seasons dialog's reviews read of the collection's downloaded files, kept between them
        (``backend.services.file_moves``)."""
        self._was = self._snapshot()

    def _snapshot(self):
        return (
            {season.id: replace(season) for season in self.seasons.values()},
            {playlist.id: tuple(getattr(playlist, name) for name in _LIST_FIELDS) for playlist in self.lists},
            {episode.id: tuple(getattr(episode, name) for name in _EPISODE_FIELDS) for episode in self.episodes.values()},
            {name: getattr(self.collection, name) for name in SETTINGS},
        )

    def changed_identifiers(self) -> dict[int, tuple[str | None, str | None]]:
        """The saved episodes whose identifier the planner changed: the one each had, and the one it has now."""
        was = self._was[2]
        return {
            episode.id: (was[episode.id][1], episode.episode_identifier) for episode in self.episodes.values()
            if episode.id in was and was[episode.id][1] != episode.episode_identifier
        }

    def new_id(self) -> int:
        self._next -= 1
        return self._next

    # Seasons

    def ordered_seasons(self) -> list[SeasonDraft]:
        return sorted(self.seasons.values(), key=lambda season: season.index)

    def season(self, season_id: int | None) -> SeasonDraft | None:
        return self.seasons.get(season_id) if season_id is not None else None

    def season_draft(
        self, *, slug: str, name: str, number: int, origin: str, season_type: str, id: int = 0,
    ) -> SeasonDraft:
        """A new season as it would be made now, apart from the copy, such as to name a file in it."""
        taken = {season.slug for season in self.seasons.values()}
        unique, suffix = slug, 2
        while unique in taken:
            unique, suffix = f"{slug}-{suffix}", suffix + 1
        return SeasonDraft(
            id=id, collection_id=self.record.id, slug=unique, name=name, season_number=number,
            index=max((x.index for x in self.seasons.values()), default=0) + 1, season_type=season_type, origin=origin,
            loose=False, created_at=self.now,
        )

    def make_season(self, *, slug: str, name: str, number: int, origin: str, season_type: str) -> SeasonDraft:
        season = self.season_draft(
            slug=slug, name=name, number=number, origin=origin, season_type=season_type, id=self.new_id(),
        )
        self.seasons[season.id] = season
        self.made.add(season.id)
        return season

    def drop_season(self, season_id: int) -> None:
        self.seasons.pop(season_id, None)
        self.gone_seasons.add(season_id)
        for playlist in self.lists:
            if playlist.season_id == season_id:
                playlist.season_id = None

    def drop_emptied(self, season_ids: set[int], *, keep_extras: bool = True) -> None:
        """Remove the seasons that every episode moved out of, so the collection shows no empty seasons."""
        from backend.types.season_types import SeasonType

        filled = {episode.season_id for episode in self.episodes.values()}
        for season_id in season_ids - filled:
            season = self.seasons.get(season_id)
            if season is not None and not (keep_extras and season.season_type == SeasonType.EXTRA.value):
                self.drop_season(season_id)

    # Episodes

    def live_episodes(self) -> list[EpisodeDraft]:
        return list(self.episodes.values())

    def in_index_order(self) -> list[EpisodeDraft]:
        return sorted(self.episodes.values(), key=lambda episode: (episode.index, episode.id))

    def add_episode(self, episode: EpisodeDraft) -> EpisodeDraft:
        self.episodes[episode.id] = episode
        return episode

    def remove_episode(self, episode: EpisodeDraft) -> None:
        """The episode leaves the collection now, and its season with it when that holds nothing else."""
        self.episodes.pop(episode.id, None)
        self.leaving.pop(episode.id, None)
        if episode.id > 0:
            self.gone[episode.id] = episode
        self.drop_emptied({episode.season_id})

    def next_index(self) -> int:
        return max((episode.index for episode in self.episodes.values()), default=0) + 1

    # Lists

    def drop_list(self, playlist: ListDraft) -> None:
        self.lists.remove(playlist)
        self.gone_lists.add(playlist.id)


def load_state(s: Session, collection: Collection, now: datetime | None = None) -> SeasonsState:
    """A copy of the collection's seasons, lists and episodes for the planner, as they are now."""
    return SeasonsState(s, collection, now)


def apply_state(s: Session, state: SeasonsState) -> dict[int, Season]:
    """Make the collection's seasons, lists and episodes what the planner made of the copy. Returns the seasons it
    made, by the id they had in the copy.

    ``s`` is a write transaction's session."""
    from backend.services.seasons import create_season_record

    record = state.record
    was_seasons, was_lists, was_episodes, was_settings = state._was
    for name in SETTINGS:
        if getattr(state.collection, name) != was_settings[name]:
            setattr(record, name, getattr(state.collection, name))
    for playlist in [playlist for playlist in record.lists if playlist.id in state.gone_lists]:
        s.delete(playlist)
    s.flush()
    seasons = {season.id: season for season in record.seasons}
    # A season keeps its place and slug until the others moved out of the way: (collection, index) and
    # (collection, slug) are unique.
    changed = [
        season for season in state.seasons.values()
        if season.id > 0 and (season.slug, season.index) != (was_seasons[season.id].slug, was_seasons[season.id].index)
    ]
    for season_id in state.gone_seasons:
        if season_id in seasons:
            seasons[season_id].slug = f"leaving-{season_id}"
            seasons[season_id].index = -season_id
    for season in changed:
        seasons[season.id].slug = f"moving-{season.id}"
        seasons[season.id].index = -season.id - 1_000_000
    s.flush()
    top = max([0, *(season.index for season in state.seasons.values())])
    made: dict[int, Season] = {}
    for offset, season in enumerate(sorted((x for x in state.seasons.values() if x.id < 0), key=lambda x: -x.id), start=1):
        created = create_season_record(
            s, collection_id=record.id, index=top + offset + len(state.seasons) + 1, slug=f"making-{-season.id}",
            name=season.name, season_number=season.season_number, origin=_origin(season.origin),
            update_collection_profiles=True,
        )
        made[season.id] = created
        seasons[created.id] = created
    real = {draft_id: season.id for draft_id, season in made.items()}

    def season_id(value: int | None) -> int | None:
        return real.get(value, value) if value is not None else None

    for draft in state.seasons.values():
        season = made[draft.id] if draft.id < 0 else seasons[draft.id]
        season.name, season.loose, season.season_number = draft.name, draft.loose, draft.season_number
    if record.feed_seasons and any(value in real for value in record.feed_seasons.values()):
        record.feed_seasons = {ref: season_id(value) for ref, value in record.feed_seasons.items()}
    lists = {playlist.id: playlist for playlist in record.lists}
    for playlist in state.lists:
        target = lists[playlist.id]
        if tuple(getattr(playlist, name) for name in _LIST_FIELDS) != was_lists.get(playlist.id):
            for name in _LIST_FIELDS:
                setattr(target, name, season_id(playlist.season_id) if name == "season_id" else getattr(playlist, name))
    s.flush()
    _apply_episodes(s, state, real, was_episodes)
    for season_id_ in sorted(state.gone_seasons):
        if season_id_ in seasons:
            s.delete(seasons[season_id_])
    s.flush()
    # Every season at its place and with its slug.
    for draft in state.seasons.values():
        season = made[draft.id] if draft.id < 0 else seasons[draft.id]
        season.slug, season.index = draft.slug, draft.index
    s.flush()
    s.expire(record, ["seasons", "lists", "episodes"])
    for draft_id, season in made.items():
        draft = state.seasons.get(draft_id)
        if draft is not None:
            draft.id = season.id
    return made


def _origin(value: str):
    from backend.types.season_types import SeasonOrigin

    return SeasonOrigin(value)


# What an episode of a video in another season has of its own, rather than of the video.
_OWN = frozenset({
    "id", "uuid", "slug", "season_id", "index", "extra_index", "episode_identifier", "created_at", "updated_at",
    "removed_from_source",
})


def _apply_episodes(s: Session, state: SeasonsState, real: dict[int, int], was: dict[int, tuple]) -> None:
    from sqlalchemy import inspect

    from backend.services.link_seasons import held_back
    from backend.services.removed_downloads import delete_episode
    from backend.utils.helpers import generate_uuid
    from task_manager.events.transactional import queue_event
    from task_manager.scheduler.transactional import queue_task_after_commit

    record = state.record
    changed = [
        episode for episode in state.episodes.values()
        if episode.id > 0 and tuple(getattr(episode, name) for name in _EPISODE_FIELDS) != was.get(episode.id)
    ]
    rows = {episode.id: episode for episode in s.scalars(select(Episode).where(Episode.id.in_(
        [episode.id for episode in changed] + list(state.gone) + list(state.leaving)
        + [episode.copy_of for episode in state.episodes.values() if episode.copy_of is not None]
    )))} if changed or state.gone or state.leaving or any(e.copy_of for e in state.episodes.values()) else {}
    # The episodes that leave give up their identifiers first.
    for episode_id in sorted(state.gone):
        delete_episode(s, rows[episode_id])
    s.flush()
    renumbered = [episode for episode in changed if episode.episode_identifier != was[episode.id][1]]
    # Identifiers are unique in a collection: out of the way first.
    for episode in renumbered:
        rows[episode.id].episode_identifier = f"renumbering.{episode.id}"
    s.flush()
    for episode in changed:
        row = rows[episode.id]
        row.season_id = real.get(episode.season_id, episode.season_id)
        row.episode_identifier = episode.episode_identifier
        row.from_link_season = episode.from_link_season
        row.removed_from_source = episode.removed_from_source
    s.flush()
    copied = [attr.key for attr in inspect(Episode).column_attrs if attr.key not in _OWN]
    added: list[Episode] = []
    slugs: set[str] = set()
    for episode in sorted(state.episodes.values(), key=lambda episode: -episode.id):
        if episode.id > 0:
            continue
        season_id = real.get(episode.season_id, episode.season_id)
        if episode.record is not None:
            row = episode.record
            row.season_id, row.episode_identifier, row.index = season_id, episode.episode_identifier, episode.index
            row.from_link_season = episode.from_link_season
        else:
            original = rows[episode.copy_of]
            season = s.get(Season, season_id)
            row = Episode(
                **{key: getattr(original, key) for key in copied}, uuid=generate_uuid(),
                slug=_placement_slug(s, record, season, episode.source_slug, slugs), season_id=season_id,
                index=episode.index, episode_identifier=episode.episode_identifier,
            )
            slugs.add(row.slug)
            added.append(row)
        s.add(row)
        s.flush()
        episode.id = row.id
    for episode in added:
        queue_event(s, "episode.added", {
            "resource_id": episode.id, "id": episode.id, "slug": episode.slug, "collection_id": record.id,
            "collection_slug": record.slug, "season_id": episode.season_id, "status": episode.publish_status,
        })
    removing = False
    now = datetime.now(timezone.utc)
    for leaving in state.leaving.values():
        row = rows[leaving.episode.id]
        if leaving.by_user:
            # The user was told the files go with it.
            for download in row.downloads:
                download.kept = False
                download.removal_answered_at = download.removal_answered_at or now
        removing = removing or not held_back(row)
    if removing:
        queue_task_after_commit(s, def_key="remove_left_episodes", resource_type="collection", resource_id=record.id)
    s.flush()


def _placement_slug(s: Session, collection: Collection, season: Season, source_slug: str, taken: set[str]) -> str:
    """A slug of its own for a video's episode in another season, which no other episode has."""
    slug = f"{collection.slug}-{season.slug}-{source_slug}"
    unique, suffix = slug, 2
    while unique in taken or s.scalar(select(func.count()).select_from(Episode).where(Episode.slug == unique)):
        unique, suffix = f"{slug}-{suffix}", suffix + 1
    return unique


__all__ = [
    "CollectionDraft", "EpisodeDraft", "Leaving", "ListDraft", "SeasonDraft", "SeasonsState", "apply_state", "load_state",
]
