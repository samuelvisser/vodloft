"""Link seasons: a collection of a creator's whole channel, on a Site with ``link_seasons``, can make the
creator's lists, its playlists, its seasons, every list or the ones the user keeps on. An artist's albums are their
lists. Each list has a season of its own, or shares one with other lists the user put together with it.

A playlist only takes videos the collection itself lists, so a video of another creator in it stays out, unless the
collection is set to add those too: they then leave again once no playlist that is a season lists them. When the
user turns that playlist or setting off, they leave files and all. When the creator takes a downloaded one out of
the playlist, it stays, and the Home page asks whether to keep it, as for a video its Site no longer has; it leaves
once the answer is not to keep it. A video in
a playlist that is a season goes to that season, and a video in several of them to the one that comes first. A video
that is in none of them goes to one season of such videos, named as their Site calls it, such as Videos, or Singles for an artist, or as the collection
can be set, to a season per upload year.

A video with files stays where it is when the playlists change, so its files keep their place. Its page says where
it belongs now, and moving it there, or renaming the collection's files with their season folders, moves its files.
"""
from __future__ import annotations

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.db.models import Collection, CollectionList, CollectionListItem, Episode, MediaDownloadBase, Season
from backend.services.season_order import arrange_seasons, link_first_videos, match_seasons_of_downloaded, season_year
from backend.services.seasons import create_season_record
from backend.services.sites import collection_site
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from backend.types.season_types import SeasonType
from backend.types.link_season_types import ListLayout, LooseVideos, NewLinkSeasonAction, LinkSeasons, ListStatus, OutsideVideos
from backend.utils.helpers import slugify
from sources import Feature, ItemRef, ListNames, SectionRef, Source, VideoDetails, get_source

logger = logging.getLogger(__name__)

# Seasons per upload year are numbered by the year, so named seasons stay below it.
_FIRST_YEAR = 1900
# How many of a creator's playlists are listed at once.
_LISTS_AT_ONCE = 4


def list_names(collection: Collection) -> ListNames:
    """What the collection's Site calls its link seasons, such as playlists, or albums in a Music collection."""
    site = collection_site(collection)
    if site is None:
        return ListNames()
    return site.music_link_season_names if collection.type == CollectionType.MUSIC.value else site.list_names


def link_seasons_on(collection: Collection) -> bool:
    """Whether the collection makes playlists of its creator its seasons: it is set to, its Site offers it, and its
    link is the creator's whole channel rather than one playlist. A collection that only holds its link seasons
    always has them on."""
    if collection.link_seasons == LinkSeasons.OFF.value:
        return False
    return offers_link_seasons(collection)


def holds_only_link_seasons(collection: Collection) -> bool:
    """Whether the collection holds nothing but the videos of its link seasons, which it may have from several Sites,
    and may go without a link of its own."""
    return collection.outside_videos == OutsideVideos.ONLY.value


def lists_playlists(collection: Collection) -> bool:
    """Whether the collection's own link is a creator's whole channel, on a Site whose playlists can be seasons, so
    its playlists are listed for it."""
    if collection.sharing_url is None:
        return False
    site = collection_site(collection)
    return site.link_seasons and get_source(collection.source_key).is_creator_page(collection.sharing_url)


def follows_creator(collection: Collection) -> bool:
    """Whether the collection is its creator's own collection, whose lists the creator finds and places: the
    collection does not look for new lists itself, and takes the ones the creator gives it."""
    creator = collection.creator
    return creator is not None and collection.id in creator.main_collection_ids


def offers_link_seasons(collection: Collection) -> bool:
    """Whether the collection's playlists could be its seasons: its Site offers it, and its link is a whole channel.
    A collection that only holds its link seasons can have them whenever its Source lists the links it is given."""
    if holds_only_link_seasons(collection):
        return get_source(collection.source_key).has(Feature.LINK_COLLECTIONS)
    return lists_playlists(collection)


def lists_by_year(collection: Collection) -> bool:
    """Whether the collection lays its lists out in seasons per upload year, rather than a season each."""
    return collection.list_layout == ListLayout.BY_YEAR.value and link_seasons_on(collection)


def loose_in_one_season(collection: Collection) -> bool:
    """Whether the videos in none of the lists go to one season of their own. With the lists laid out by year, they
    join the year seasons."""
    return collection.loose_videos == LooseVideos.ONE_SEASON.value and collection.list_layout != ListLayout.BY_YEAR.value


def is_season(collection: Collection, playlist: CollectionList) -> bool:
    """Whether the playlist is one of the collection's seasons, as the collection is set."""
    if collection.link_seasons == LinkSeasons.ALL.value:
        return True
    return playlist.enabled and playlist.status == ListStatus.KNOWN.value


def active_lists(s: Session, collection: Collection) -> list[CollectionList]:
    """The playlists that are seasons, in the order that decides which one keeps a video several of them have: the
    order of their seasons, then the playlist whose first video came out first."""
    if not link_seasons_on(collection):
        return []
    active = [playlist for playlist in collection.lists if is_season(collection, playlist)]
    firsts = link_first_videos(s, collection)
    never = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(active, key=lambda playlist: (
        playlist.season is None, playlist.season.index if playlist.season is not None else 0,
        firsts.get(playlist.id, never), playlist.site_position if playlist.added_by_user else -playlist.site_position,
    ))


def _holders(s: Session, playlists: list[CollectionList]) -> dict[str, CollectionList]:
    """The playlist that keeps each video, by the video's slug."""
    holders: dict[str, CollectionList] = {}
    for playlist in reversed(playlists):
        for slug in s.scalars(select(CollectionListItem.source_slug).where(CollectionListItem.list_id == playlist.id)):
            holders[slug] = playlist
    return holders


def adds_outside_videos(collection: Collection) -> bool:
    """Whether the collection adds the videos of its link seasons that its own link does not list. A collection that
    only holds its link seasons adds every video they list, as its own link is not listed."""
    return link_seasons_on(collection) and collection.outside_videos in (OutsideVideos.ADD.value, OutsideVideos.ONLY.value)


@dataclass(frozen=True)
class LinkListing:
    """What the Source says about the playlists of a collection's creator, asked before the write transaction."""

    playlists: list[SectionRef] | None
    """Every playlist of the creator, newest first; None when they could not be listed."""
    items: dict[str, tuple[ItemRef, ...]] = field(default_factory=dict)
    """The videos of each playlist that is a season, in its order, by its ref. A playlist that could not be listed is
    left out."""
    outside: list[VideoDetails] = field(default_factory=list)
    """The videos of the playlists that are seasons that the collection's own link does not list, looked up, for a
    collection that adds them."""


def known_video_slugs(s: Session, collection: Collection, also: frozenset[str] = frozenset()) -> frozenset[str]:
    return frozenset(s.scalars(select(Episode.video_slug).where(Episode.collection_id == collection.id))) | also


def list_lists(s: Session, collection: Collection, source: Source, also: frozenset[str] = frozenset()) -> LinkListing:
    """Ask the Source for the creator's playlists and the videos of those that are seasons, and for a collection
    that adds them, look up the videos it has not got that are neither in ``also``, the ones its own link just
    listed. Slow, so no transaction stays open."""
    # The creator's daily look finds the lists of its own collection; the collection only lists their videos.
    url = collection.sharing_url if lists_playlists(collection) and not follows_creator(collection) else None
    every = collection.link_seasons == LinkSeasons.ALL.value
    adds_new = every or collection.new_link_seasons == NewLinkSeasonAction.ADD.value or not collection.lists
    known = {playlist.ref: (playlist.url, playlist.enabled and playlist.status == ListStatus.KNOWN.value)
             for playlist in collection.lists}
    adds_outside = adds_outside_videos(collection)
    known_slugs = known_video_slugs(s, collection, also) if adds_outside else frozenset()
    s.rollback()
    playlists = None
    if url is not None:
        try:
            playlists = source.season_lists(url)
        except Exception as exc:
            logger.info("Could not list the playlists of %s: %s", url, exc)
    wanted = {ref: playlist_url for ref, (playlist_url, on) in known.items() if every or on}
    for playlist in playlists or ():
        if playlist.ref not in known and adds_new:
            wanted[playlist.ref] = playlist.url
    items: dict[str, tuple[ItemRef, ...]] = {}

    def list_one(playlist_url: str) -> tuple[ItemRef, ...] | None:
        try:
            return source.list_items(playlist_url)
        except Exception as exc:
            logger.info("Could not list the playlist %s: %s", playlist_url, exc)
            return None

    # A creator can have hundreds of playlists, each a lookup of a second or more, so a few are listed at once. Each
    # runs in a copy of this context, which tells the Source's pacing whose requests they are.
    with ThreadPoolExecutor(max_workers=_LISTS_AT_ONCE, thread_name_prefix="list-items") as pool:
        listed = {ref: pool.submit(contextvars.copy_context().run, list_one, playlist_url) for ref, playlist_url in wanted.items()}
        for ref, future in listed.items():
            if (found := future.result()) is not None:
                items[ref] = found
    return LinkListing(playlists, items, _look_up_outside(source, adds_outside, known_slugs, items))


def _look_up_outside(
    source: Source, adds: bool, known: frozenset[str], items: dict[str, tuple[ItemRef, ...]],
) -> list[VideoDetails]:
    if not adds:
        return []
    wanted = {item.slug: item for listed in items.values() for item in listed if item.slug not in known}
    if not wanted:
        return []
    try:
        found = source.item_details(list(wanted.values()))
    except Exception as exc:
        logger.info("Could not look up the videos of the playlists: %s", exc)
        return []
    # A video that could not be looked up now is tried again next time.
    return [details for details in found.values() if details is not None]


def save_lists(s: Session, collection: Collection, listing: LinkListing) -> list[CollectionList]:
    """Store the creator's playlists and what the seasons among them hold. A playlist the creator added since the
    collection was set up is a season, is left off, or waits for the user's choice, as the collection says. Returns
    the ones that wait. A playlist the Site no longer lists stays, with what it held.

    ``s`` is a write transaction's session."""
    known = {playlist.ref: playlist for playlist in collection.lists}
    first = not known
    every = collection.link_seasons == LinkSeasons.ALL.value
    action = NewLinkSeasonAction(collection.new_link_seasons)
    asked: list[CollectionList] = []
    for position, found in enumerate(listing.playlists or ()):
        playlist = known.get(found.ref)
        if playlist is None:
            # The playlists the creator had when the collection was set up are all seasons to begin with.
            asks = not first and not every and action is NewLinkSeasonAction.ASK
            playlist = CollectionList(
                ref=found.ref, url=found.url, title=found.title, image_path=found.image_url, item_count=found.item_count,
                site_position=position, enabled=first or every or action is NewLinkSeasonAction.ADD,
                status=(ListStatus.NEW if asks else ListStatus.KNOWN).value,
            )
            collection.lists.append(playlist)
            known[found.ref] = playlist
            if asks:
                asked.append(playlist)
            continue
        for name, value in (
            ("title", found.title), ("url", found.url), ("image_path", found.image_url), ("item_count", found.item_count),
            ("site_position", position),
        ):
            if value is not None and getattr(playlist, name) != value:
                setattr(playlist, name, value)
    s.flush()
    for ref, listed in listing.items.items():
        playlist = known.get(ref)
        if playlist is None:
            continue
        s.execute(delete(CollectionListItem).where(CollectionListItem.list_id == playlist.id))
        s.add_all(
            CollectionListItem(list_id=playlist.id, source_slug=item.slug, position=position)
            for position, item in enumerate(listed)
        )
    s.flush()
    return asked


class SeasonNumbers:
    """The episode numbers each season of the collection already uses."""

    def __init__(self, s: Session):
        self._s = s
        self._taken: dict[int, set[int]] = {}

    def _of(self, season: Season) -> set[int]:
        if season.id not in self._taken:
            taken = set()
            for identifier in self._s.scalars(select(Episode.episode_identifier).where(Episode.season_id == season.id)):
                number = (identifier or "").rpartition("E")[2]
                if number.isdigit():
                    taken.add(int(number))
            self._taken[season.id] = taken
        return self._taken[season.id]

    def take(self, season: Season, wanted: int | None) -> int:
        """The Source's own episode number, unless the season already has an episode with it."""
        taken = self._of(season)
        number = wanted if wanted is not None and wanted not in taken else max(taken, default=0) + 1
        taken.add(number)
        return number


class SeasonFinder:
    """Finds the collection's seasons per year and playlist seasons, makes them when it has none yet, and moves
    episodes between them."""

    def __init__(self, s: Session, collection: Collection, now: datetime | None = None):
        self._s, self._collection, self._now = s, collection, now or datetime.now(timezone.utc)
        # A Source's own season is found by its slug, a season per year by its year, which is its slug too.
        self._by_slug = {season.slug: season for season in collection.seasons}
        self._by_year = {season_year(season): season for season in collection.seasons if season_year(season) is not None}
        self.numbers = SeasonNumbers(s)
        self._loose_one = link_seasons_on(collection) and loose_in_one_season(collection)

    def create(self, *, slug: str, name: str, number: int) -> Season:
        collection = self._collection
        if collection.custom_season_order:
            # The user's order stays: a new season goes last.
            number = max((x.season_number for x in collection.seasons if x.season_type == SeasonType.NORMAL.value), default=0) + 1
        taken = {season.slug for season in collection.seasons}
        unique, suffix = slug, 2
        while unique in taken:
            unique, suffix = f"{slug}-{suffix}", suffix + 1
        season = create_season_record(
            self._s, collection_id=collection.id, index=max((x.index for x in collection.seasons), default=0) + 1,
            slug=unique, name=name, season_number=number, update_collection_profiles=True,
        )
        self._s.refresh(collection)
        self._by_slug[season.slug] = season
        if season_year(season) is not None:
            self._by_year[season_year(season)] = season
        return season

    def _named_number(self) -> int:
        """The number a new named season gets: after the other named ones, below the seasons per year."""
        return max(
            (season.season_number for season in self._collection.seasons if 0 < season.season_number < _FIRST_YEAR),
            default=0,
        ) + 1

    def loose_season(self) -> Season:
        """The one season of the videos in none of the playlists that are seasons, named as their Site calls it, such
        as Videos, or Singles for an artist."""
        season = next((season for season in self._collection.seasons if season.loose), None)
        if season is None:
            name = list_names(self._collection).loose_season
            season = self.create(slug=name.lower(), name=name, number=self._named_number())
            season.loose = True
            self._s.flush()
        return season

    def home_season(self, published_at: datetime | None) -> Season:
        """Where a new video in no playlist goes: the one season of such videos, or its season per year."""
        if self._loose_one:
            return self.loose_season()
        return self.year_season(published_at)

    def year_season(self, published_at: datetime | None) -> Season:
        year = (published_at or self._now).year
        return self._by_year.get(year) or self.create(slug=str(year), name=str(year), number=year)

    def list_season(self, playlist: CollectionList) -> Season:
        """A playlist's season, made when the playlist gets its first video."""
        if playlist.season is None:
            number = self._named_number()
            playlist.season = self.create(slug=slugify(playlist.title) or str(number), name=playlist.title, number=number)
            self._s.flush()
        return playlist.season

    def own_season(self, name: str) -> Season:
        """A season of its own, such as for a video split by chapter."""
        number = self._named_number()
        return self.create(slug=slugify(name) or str(number), name=name, number=number)

    def move(self, episode: Episode, season: Season) -> None:
        """Move an episode to another season. A seasonal number follows its new season."""
        if episode.season_id == season.id:
            return
        episode.season_id = season.id
        if (
            self._collection.episode_identifier == EpisodeIdentifier.SEASONAL.value
            and (episode.episode_identifier or "").startswith("ep.S")
        ):
            episode.episode_identifier = f"ep.S{season.season_number:02d}E{self.numbers.take(season, None):02d}"


@dataclass(frozen=True)
class Belonging:
    """Where a video belongs now that the playlists changed."""

    link: CollectionList | None = None
    """The link season it belongs in, or None for the season of videos in no playlist."""
    loose: bool = False
    """With no playlist: the one season of videos in no playlist, rather than its season per year."""


def _with_files(s: Session, collection: Collection) -> set[int]:
    return set(s.scalars(
        select(MediaDownloadBase.media_item_id).join(Episode, Episode.id == MediaDownloadBase.media_item_id)
        .where(Episode.collection_id == collection.id)
    ))


class _Places:
    """Where each of the collection's videos belongs: the season of the first playlist that has it, or else the season
    of videos in no playlist, as the collection is set. Only videos in such a season move: a Source's own season and a
    video split by chapter stay."""

    def __init__(self, s: Session, collection: Collection, left: frozenset[int] = frozenset()):
        on = link_seasons_on(collection)
        self.holders = _holders(s, active_lists(s, collection)) if on else {}
        playlist_ids = {playlist.season_id for playlist in collection.lists if playlist.season_id is not None}
        self.loose_one = on and loose_in_one_season(collection)
        self.by_year = lists_by_year(collection)
        # A collection that only holds its link seasons has no season of videos in none of them: those leave.
        self.only = holds_only_link_seasons(collection)
        self.loose_ids = {season.id for season in collection.seasons if season.loose}
        year_ids = {season.id for season in collection.seasons if season_year(season) is not None}
        # A season that its lists just left, for another list's season, empties too.
        self.movable = playlist_ids | self.loose_ids | year_ids | left
        self.anything = on or bool(playlist_ids) or bool(self.loose_ids)

    def belonging(self, episode: Episode) -> Belonging | None:
        """Where the episode belongs, when that is not where it is."""
        if episode.part_of is not None or episode.season_id not in self.movable:
            return None
        holder = self.holders.get(episode.source_slug)
        if holder is not None and self.by_year:
            # The list decides that the video is in; its date decides the season.
            return None if season_is_year(episode.season) and episode.season_id not in self.loose_ids else Belonging()
        if holder is not None:
            return None if holder.season_id is not None and holder.season_id == episode.season_id else Belonging(holder)
        if self.only:
            return None
        if self.loose_one:
            return None if episode.season_id in self.loose_ids else Belonging(loose=True)
        return None if episode.season_id not in self.loose_ids and season_is_year(episode.season) else Belonging()


def season_is_year(season: Season | None) -> bool:
    return season is not None and season_year(season) is not None


def _season_for(finder: "SeasonFinder", episode: Episode, belonging: Belonging) -> Season:
    if belonging.link is not None:
        return finder.list_season(belonging.link)
    return finder.loose_season() if belonging.loose else finder.year_season(episode.published_date)


def place_in_link_seasons(
    s: Session, collection: Collection, *, with_files: bool | set[int] = False, now: datetime | None = None,
    by_user: bool = False, drop: bool = True, left: frozenset[int] = frozenset(),
) -> int:
    """Put each of the collection's videos where it belongs: in the season of the first playlist that has it, or in
    the season of videos in no playlist. A video with files stays where it is, unless ``with_files`` is True or holds
    its id. Returns how many moved. ``by_user`` says the user changed the playlists, so the videos that leave take
    their files with them. The videos that left the collection go, unless ``drop`` is False because the playlists
    are about to be listed again. ``left`` holds the seasons that the user took lists out of, whose videos move too.

    ``s`` is a write transaction's session."""
    if drop:
        _drop_outside(s, collection, by_user=by_user)
    places = _Places(s, collection, left)
    if not places.anything:
        return 0
    kept = set() if with_files is True else _with_files(s, collection) - (with_files or set())
    finder = SeasonFinder(s, collection, now)
    moved = 0
    episodes = s.scalars(
        select(Episode).where(Episode.collection_id == collection.id, Episode.part_of.is_(None)).order_by(Episode.index)
    ).all()
    left: set[int] = set()
    for episode in episodes:
        if episode.from_link_season and episode.removed_from_source and episode.source_slug in places.holders:
            # A playlist that is a season lists it again, so it is back at its Site.
            episode.removed_from_source = False
        if episode.id in kept:
            continue
        belonging = places.belonging(episode)
        if belonging is None:
            continue
        season = _season_for(finder, episode, belonging)
        if season.id != episode.season_id:
            left.add(episode.season_id)
            finder.move(episode, season)
            moved += 1
    s.flush()
    _drop_emptied(s, collection, left)
    arrange_seasons(s, collection)
    return moved


def leaving_outside(s: Session, collection: Collection) -> list[Episode]:
    """The videos the collection added from its link seasons that no link season that is on lists any more, or all of
    them when it no longer adds such videos. They leave the collection, files and all."""
    held = _holders(s, active_lists(s, collection)) if adds_outside_videos(collection) else {}
    return [
        episode for episode in s.scalars(
            select(Episode).where(Episode.collection_id == collection.id, Episode.from_link_season)
        )
        if episode.video_slug not in held
    ]


def outside_only_in(s: Session, collection: Collection) -> dict[int, tuple[int, int]]:
    """For each link season, how many of the videos the collection added from the link seasons only it lists, and so
    would leave with it, and how many of those have files. By link season id."""
    active = {link.id for link in active_lists(s, collection)}
    with_files = _with_files(s, collection)
    listed: dict[str, list[int]] = {}
    for link_id, slug in s.execute(
        select(CollectionListItem.list_id, CollectionListItem.source_slug)
        .join(CollectionList, CollectionList.id == CollectionListItem.list_id)
        .where(CollectionList.collection_id == collection.id)
    ):
        if link_id in active:
            listed.setdefault(slug, []).append(link_id)
    counts: dict[int, tuple[int, int]] = {}
    for episode_id, slug in s.execute(
        select(Episode.id, Episode.video_slug).where(Episode.collection_id == collection.id, Episode.from_link_season)
    ):
        holding = listed.get(slug, ())
        if len(holding) == 1:
            count, files = counts.get(holding[0], (0, 0))
            counts[holding[0]] = (count + 1, files + (episode_id in with_files))
    return counts


def remove_left_episode(s: Session, episode: Episode) -> None:
    """Remove an episode that left its collection, with its download records. Its files are gone already.

    ``s`` is a write transaction's session."""
    from backend.services.removed_downloads import delete_episode

    collection, season_id = episode.collection, episode.season_id
    delete_episode(s, episode)
    _drop_emptied(s, collection, {season_id})


def held_back(episode: Episode) -> bool:
    """Whether a video that left its collection keeps its files for now: one of its downloads is kept, or waits for
    the user to say whether to keep it."""
    from backend.services.removed_downloads import awaits_keep_answer

    return any(
        download.kept or awaits_keep_answer(download, removed_from_source=episode.removed_from_source)
        for download in episode.downloads
    )


def _drop_outside(s: Session, collection: Collection, *, by_user: bool = False) -> int:
    """Remove the videos that left the collection: at once when they have no files, and otherwise by a task that
    deletes their files first. A downloaded video only leaves with its files when the user changed the playlists;
    one the creator took out of a playlist stays, and the Home page asks whether to keep it. Returns how many went
    now.

    ``s`` is a write transaction's session."""
    from task_manager.scheduler.transactional import queue_task_after_commit

    leaving = leaving_outside(s, collection)
    if not leaving:
        return 0
    with_files = _with_files(s, collection)
    gone = [episode for episode in leaving if episode.id not in with_files]
    now = datetime.now(timezone.utc)
    removing = False
    for episode in leaving:
        if episode.id not in with_files:
            continue
        if by_user:
            # The user was told the files go with it.
            for download in episode.downloads:
                download.kept = False
                download.removal_answered_at = download.removal_answered_at or now
        elif not episode.removed_from_source:
            # As for a video its Site no longer has: the Home page asks whether to keep the files.
            episode.removed_from_source = True
        removing = removing or not held_back(episode)
    if removing:
        queue_task_after_commit(s, def_key="remove_left_episodes", resource_type="collection", resource_id=collection.id)
    for episode in gone:
        remove_left_episode(s, episode)
    return len(gone)


def _drop_emptied(s: Session, collection: Collection, season_ids: set[int]) -> None:
    """Remove the seasons that every video moved out of, so the collection shows no empty seasons."""
    filled = set(s.scalars(select(Episode.season_id).where(Episode.season_id.in_(season_ids)).distinct()))
    emptied = [
        season for season in collection.seasons
        if season.id in season_ids - filled and season.season_type != SeasonType.EXTRA.value
    ]
    for season in emptied:
        s.delete(season)
    if emptied:
        s.flush()
        s.expire(collection, ["seasons", "lists"])


def belongs_elsewhere(s: Session, episode: Episode) -> Belonging | None:
    """Where a video belongs now, when its collection's playlists put it in another season than the one it is in.
    None when it is where it belongs."""
    places = _Places(s, episode.collection)
    return places.belonging(episode) if places.anything else None


def moved_episodes(s: Session, collection: Collection) -> list[Episode]:
    """The collection's videos that its playlists put in another season than the one they are in: downloaded ones,
    which wait for the user to move them, since moving renames their files."""
    places = _Places(s, collection)
    if not places.anything:
        return []
    episodes = s.scalars(
        select(Episode).where(Episode.collection_id == collection.id, Episode.season_id.in_(places.movable))
        .order_by(Episode.id)
    )
    return [episode for episode in episodes if places.belonging(episode) is not None]


def move_to_where_it_belongs(s: Session, episode: Episode) -> bool:
    """Move a video, files and all, to the season its collection's playlists put it in now. Returns whether it moved.

    ``s`` is a write transaction's session."""
    belonging = belongs_elsewhere(s, episode)
    if belonging is None:
        return False
    collection = episode.collection
    finder = SeasonFinder(s, collection)
    left = episode.season_id
    finder.move(episode, _season_for(finder, episode, belonging))
    s.flush()
    _drop_emptied(s, collection, {left})
    arrange_seasons(s, collection)
    # Its files move into its season's folder, so it takes that season's number.
    match_seasons_of_downloaded(s, collection, {episode.id})
    return True
