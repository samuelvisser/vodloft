"""Link seasons: a channel collection, of a creator's whole channel on a Site with ``link_seasons``, can make the
channel's lists, its playlists, its seasons, every list or the ones the user keeps on. An artist's albums are their
lists. Each list has a season of its own, or shares one with other lists the user put together with it.

A playlist only takes videos the collection itself lists, so another channel's video in it stays out, unless the
collection is set to add those too: they then leave again once no playlist that is a season lists them. When the
user turns that playlist or setting off, they leave files and all. When the channel takes a downloaded one out of
the playlist, it stays, and the Home page asks whether to keep it, as for a video its Site no longer has; it leaves
once the answer is not to keep it. A video in
a playlist that is a season goes to that season, and a video in several of them to the one that comes first, or, in a
collection set to repeat it, such as an artist's albums, to each of them, as an episode with files of its own.

The channel's own videos, those of its feeds, also have a season: the channel season. It holds every one of them,
named after the Site's channel collections, such as Channel, or as the collection can be set, only those in none of
its lists, named as their Site calls them, such as Videos, or Singles for an artist. The collection can also be set to
give the videos in none of its lists a season per upload year instead.

Everything here is about one collection: two collections never keep a video from each other.

A video with files stays where it is when the playlists change, so its files keep their place. Its page says where
it belongs now, and moving it there, or renaming the collection's files with their season folders, moves its files.
"""
from __future__ import annotations

import contextvars
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.db.models import Collection, CollectionList, CollectionListItem, Episode
from backend.services.season_order import arrange, link_first_videos, season_year
from backend.services.file_moves import FileMoves, number_in
from backend.services.season_state import (
    EpisodeDraft, Leaving, ListDraft, SeasonDraft, SeasonsState, apply_state, load_state,
)
from backend.services.new_lists import ListKind, NewListSetting, list_kinds, new_link_seasons_settings
from backend.services.sites import collection_creator_names, collection_names, collection_site, collection_words
from backend.types.collection_contracts import collection_contract
from backend.types.collection_types import EpisodeIdentifier
from backend.types.season_types import SeasonOrigin, SeasonType
from backend.types.link_season_types import (
    CollectionKind, LooseVideos, NewLinkSeasonAction, LinkSeasons, ListStatus, OutsideVideos, RepeatVideos,
)
from backend.utils.helpers import slugify
from backend.utils.season_ordering import season_type_from_name
from sources import MAIN_TAG, Feature, ItemRef, ListOrder, Names, SectionKind, SectionRef, SectionType, Source, VideoDetails, get_source
from sources.ytdlp_options import keep_call_options

logger = logging.getLogger(__name__)

# Seasons per upload year are numbered by the year, so named seasons stay below it.
_FIRST_YEAR = 1900
# How many of a channel's playlists are listed at once.
_LISTS_AT_ONCE = 4


def section_list_names(collection: Collection) -> Names:
    """What the collection's Site calls the lists its link seasons come from, such as playlists, or albums and
    playlists on SoundCloud."""
    return collection_site(collection).section_list_names


def holds_whole_channel(collection: Collection) -> bool:
    """Whether the collection's channel season holds every video of its feeds, also those its lists have: it is set
    to, or none of its lists are seasons. Only on a Site whose lists can be seasons: elsewhere, such as on The Daily
    Wire, seasons are the Site's own."""
    if not (channel_season_offered(collection) and loose_in_one_season(collection)):
        return False
    return collection.loose_videos == LooseVideos.EVERYTHING.value or not lists_are_seasons(collection)


def channel_season_offered(collection: Collection) -> bool:
    """Whether the videos of the collection's feeds can be in one season of their own, the channel season, rather than
    in a season per upload year: it is a channel collection on a Site whose lists can be seasons, and it lists its
    own link."""
    return lists_playlists(collection) and lists_own_link(collection)


def loose_season_name(collection: Collection) -> str:
    """The name of the channel season: the Site's name for a channel collection, such as Channel, when it holds the
    whole channel; otherwise the name of the videos in none of the collection's lists, Videos, or as its Site names
    them, such as Singles on SoundCloud, unless its type names them itself, such as Singles in a Music collection."""
    site = collection_site(collection)
    if holds_whole_channel(collection):
        return site.channel_collection_names.singular.capitalize()
    return collection_contract(collection.type).loose_season_on(site)


def link_seasons_on(collection: Collection) -> bool:
    """Whether the collection makes playlists of its channel its seasons: it is set to, its Site offers it, and its
    link is a whole channel rather than one playlist. A collection that only holds its link seasons always has them
    on."""
    if collection.link_seasons == LinkSeasons.OFF.value:
        return False
    return offers_link_seasons(collection)


def holds_only_link_seasons(collection: Collection) -> bool:
    """Whether the collection holds nothing but the videos of its link seasons, which it may have from several Sites,
    and may go without a link of its own."""
    return collection.outside_videos == OutsideVideos.ONLY.value


def made_from_list(collection: Collection) -> bool:
    """Whether the collection is made from one list, such as a playlist or an album, with its videos in the list's
    order: the list is its one season, or its videos go in a season per upload year, as the collection is set."""
    return collection.kind == CollectionKind.LIST.value and collection.sharing_url is not None and not holds_only_link_seasons(collection)


def numbered_in_list_order(collection: Collection) -> bool:
    """Whether the collection numbers and shows its videos in the order they were added, which is its list's order:
    a collection made from one list on a Site that lists in an order VODLoft trusts."""
    return made_from_list(collection) and collection_site(collection).list_order is not ListOrder.NONE


def list_in_one_season(collection: Collection) -> bool:
    """Whether the collection made from one list has the list as its one season, rather than a season per year."""
    return made_from_list(collection) and collection.loose_videos == LooseVideos.ONE_SEASON.value


def lists_own_link(collection: Collection) -> bool:
    """Whether the collection's own link lists its videos: it has one, it holds more than its link seasons, and it
    takes at least one of its channel's feeds."""
    return collection.sharing_url is not None and not holds_only_link_seasons(collection) and collection.feeds != []


def own_feeds(collection: Collection) -> frozenset[str] | None:
    """The channel's feeds the collection lists, or None when it lists all that its link lists."""
    return frozenset(collection.feeds) if collection.feeds is not None else None


def feed_seasons(collection: Collection) -> dict[str, str]:
    """The feeds of the collection's channel that are a season of their own, by the episode tag their videos get, with
    the feed's ref: such as a YouTube channel's Shorts. Only for a collection that lists its own link, and only feeds
    it takes."""
    chosen = collection.feed_seasons or {}
    if not chosen or not lists_own_link(collection):
        return {}
    taken = own_feeds(collection)
    return {
        type_.episode_tag: type_.feed_ref for type_ in collection_site(collection).types_of(SectionKind.FEED)
        if type_.feed_ref in chosen and (taken is None or type_.feed_ref in taken)
    }


def feed_season_ids(collection: Collection) -> dict[str, int]:
    """The season of each feed that is a season of its own and has one yet, by the feed's ref."""
    known = {season.id for season in collection.seasons}
    return {
        ref: season_id for ref, season_id in (collection.feed_seasons or {}).items()
        if season_id is not None and season_id in known
    }


def lists_playlists(collection: Collection) -> bool:
    """Whether the collection's own link is a whole channel, on a Site whose playlists can be seasons, so its
    playlists are listed for it."""
    url = collection.sharing_url
    if url is None:
        return False
    site = collection_site(collection)
    return (collection.kind == CollectionKind.CHANNEL.value and site.link_seasons
            and get_source(collection.source_key).is_creator_page(url))


def offers_link_seasons(collection: Collection) -> bool:
    """Whether the collection's playlists could be its seasons: its Site offers it, and its link is a whole channel.
    A collection that only holds its link seasons can have them whenever its Source lists the links it is given."""
    if holds_only_link_seasons(collection) and get_source(collection.source_key).has(Feature.LINK_COLLECTIONS):
        return True
    return lists_playlists(collection)


def lists_are_seasons(collection: Collection) -> bool:
    """Whether any list of the collection is a season of its own: its lists are on, and not every one of them is part
    of the collection, as a feed is. With none, the collection's own videos are grouped as if it had no lists."""
    if not link_seasons_on(collection):
        return False
    return any(is_season(collection, playlist) for playlist in collection.lists)


def repeats_videos(collection: Collection) -> bool:
    """Whether a video in several of the collection's seasons, such as those of its lists, gets an episode in each."""
    return collection.repeat_videos == RepeatVideos.EACH_SEASON.value


def loose_in_one_season(collection: Collection) -> bool:
    """Whether what is part of the collection, the videos in no season of their own, goes to one season, which holds
    the whole channel when it is set to, rather than a season per upload year."""
    return collection.loose_videos in (LooseVideos.ONE_SEASON.value, LooseVideos.EVERYTHING.value)


def loose_season_on(collection: Collection) -> bool:
    """Whether the collection has a season of the videos in none of its lists that are seasons: its lists are
    seasons, or it is a channel collection set to keep its feeds in one season."""
    return (link_seasons_on(collection) or channel_season_offered(collection)) and loose_in_one_season(collection)


def is_in(collection: Collection, playlist: CollectionList) -> bool:
    """Whether the playlist is in the collection, as the collection is set: as one of its seasons, or with its videos
    part of the collection. One that waits for the user's choice is not in yet."""
    return playlist.enabled and playlist.status == ListStatus.KNOWN.value


def is_season(collection: Collection, playlist: CollectionList) -> bool:
    """Whether the playlist is one of the collection's seasons, as the collection is set. One that is not a season
    adds its videos to the collection's other seasons."""
    return playlist.as_season and is_in(collection, playlist)


def lists_in(collection: Collection) -> list[CollectionList]:
    """The playlists in the collection, whether or not they are seasons, when its playlists are on."""
    if not link_seasons_on(collection):
        return []
    return [playlist for playlist in collection.lists if is_in(collection, playlist)]


def active_lists(state: SeasonsState) -> list[ListDraft]:
    """The playlists that are seasons, in the order that decides which one keeps a video several of them have: the
    order of their seasons, then the playlist whose first video came out first."""
    collection = state.collection
    if not link_seasons_on(collection):
        return []
    active = [playlist for playlist in collection.lists if is_season(collection, playlist)]
    firsts = link_first_videos(state)
    never = datetime.max.replace(tzinfo=timezone.utc)

    def key(playlist: ListDraft):
        season = state.season(playlist.season_id)
        return (
            season is None, season.index if season is not None else 0, firsts.get(playlist.id, never),
            playlist.site_position if playlist.added_by_user else -playlist.site_position,
        )

    return sorted(active, key=key)


def _holders(playlists: list[ListDraft]) -> dict[str, ListDraft]:
    """The playlist that keeps each video, by the video's slug."""
    return {slug: lists[0] for slug, lists in _every_holder(playlists).items()}


def _every_holder(playlists: list[ListDraft]) -> dict[str, list[ListDraft]]:
    """The playlists that have each video, in the order of ``playlists``, by the video's slug: one for each season,
    the first, where several share one."""
    found: dict[str, list[ListDraft]] = {}
    seasons: dict[str, set] = {}
    for playlist in playlists:
        season = playlist.season_id if playlist.season_id is not None else ("list", playlist.id)
        for slug in playlist.items:
            if season not in seasons.setdefault(slug, set()):
                seasons[slug].add(season)
                found.setdefault(slug, []).append(playlist)
    return found


def holder_titles(state: SeasonsState) -> dict[str, str]:
    """The title of the list in the collection that keeps each video, by the video's slug."""
    return {slug: playlist.title for slug, playlist in _holders(lists_in(state.collection)).items()}


def adds_outside_videos(collection: Collection) -> bool:
    """Whether the collection adds the videos of its link seasons that its own link does not list. A collection that
    only holds its link seasons adds every video they list, as its own link is not listed."""
    return link_seasons_on(collection) and collection.outside_videos in (OutsideVideos.ADD.value, OutsideVideos.ONLY.value)


@dataclass(frozen=True)
class LinkListing:
    """What the Sources say about the playlists of a collection, asked before the write transaction."""

    playlists: list[SectionRef] | None
    """Every playlist of the collection's channel, newest first; None when they could not be listed, or it has no
    channel."""
    items: dict[str, tuple[ItemRef, ...]] = field(default_factory=dict)
    """The videos of each playlist that is a season, in its order, by its ref. A playlist that could not be listed is
    left out."""
    outside: list[VideoDetails] = field(default_factory=list)
    """The videos of the playlists that are seasons that the collection's own link does not list, looked up, for a
    collection that adds them."""
    sources: dict[str, str] = field(default_factory=dict)
    """The Source that looked up each video of ``outside``, by its slug: the one of the list it is in."""


def collection_list_kinds(collection: Collection) -> list[ListKind]:
    """The kinds of list of the collection's Site, each with a setting of its own for new ones."""
    return list_kinds(collection_site(collection))


def collection_new_lists(collection: Collection) -> list[NewListSetting]:
    """What the collection does with a new list of each kind of its Site."""
    return new_link_seasons_settings(
        collection_list_kinds(collection), collection.new_lists,
        albums_only=collection_contract(collection.type).album_lists,
    )


def seasons_plan(collection: Collection) -> str:
    """What a collection's settings make its seasons, in words, such as for a collection about to be added: each list
    a season, what goes in the channel season, or a season per upload year."""
    words = collection_words(collection)
    season, episodes = words.season, words.episode.plural
    if list_in_one_season(collection):
        return f"The {collection_names(collection).singular} is one {season.singular} in VODLoft, its {episodes} in its order."
    if not lists_playlists(collection) or collection.link_seasons == LinkSeasons.OFF.value:
        if holds_whole_channel(collection):
            return f"VODLoft puts every {words.episode.singular} in one {season.singular}, {loose_season_name(collection)}."
        return f"VODLoft puts the {episodes} of each upload year in their own {season.singular}."
    settings = collection_new_lists(collection)
    actions = {setting.key: setting.action for setting in settings}
    taken = [s.kind.names for s in settings if actions[s.key] == NewLinkSeasonAction.ADD.value]
    skipped = [s.kind.names for s in settings if actions[s.key] == NewLinkSeasonAction.IGNORE.value]
    contents = [s.kind.names for s in settings if actions[s.key] == NewLinkSeasonAction.CONTENTS.value]
    creator = collection_creator_names(collection).singular
    sentences = []
    if taken:
        lists = Names.joined(taken)
        sentences.append(f"Every {creator} {lists.singular} becomes {season.a} in VODLoft.")
    if contents:
        sentences.append(f"The {episodes} of every {creator} {Names.joined(contents).singular} are part of the "
                         f"{collection_names(collection).singular}.")
    if skipped:
        sentences.append(f"{Names.joined(skipped).plural.capitalize()} are ignored.")
    if collection.loose_videos == LooseVideos.BY_YEAR.value:
        sentences.append(f"The {episodes} in none of them go in {season.a} per upload year.")
    elif holds_whole_channel(collection):
        also = f", also those in {Names.joined(taken).a}" if taken else ""
        sentences.append(f"{loose_season_name(collection)} holds every {words.episode.singular} of the "
                         f"{collection_names(collection).singular}{also}.")
    else:
        sentences.append(f"{episodes.capitalize()} in none of them go in {loose_season_name(collection)}.")
    return " ".join(sentences)


def _new_list_actions(collection: Collection):
    """What the collection does with a new list, by the list: a function of its ``SectionRef``. When the collection
    is set up, it takes every list but those of a kind it skips; when it skips every kind, that is about the lists to
    come, and it takes all it found."""
    actions = {setting.key: NewLinkSeasonAction(setting.action) for setting in collection_new_lists(collection)}
    if not collection.lists and all(action is NewLinkSeasonAction.IGNORE for action in actions.values()):
        actions = dict.fromkeys(actions, NewLinkSeasonAction.ASK)
    return lambda found: actions.get(found.type.key, NewLinkSeasonAction.ASK)


def known_video_slugs(s: Session, collection: Collection, also: frozenset[str] = frozenset()) -> frozenset[str]:
    return frozenset(s.scalars(select(Episode.video_slug).where(Episode.collection_id == collection.id))) | also


def list_lists(
    s: Session, collection: Collection, source: Source, also: frozenset[str] = frozenset(),
    listed: Callable[[int, int], None] | None = None,
) -> LinkListing:
    """Ask the collection's Source for its channel's playlists, and each list's Source for the videos of the lists
    that are seasons; for a collection that adds them, look up the videos it has not got that are neither in
    ``also``, the ones its own link just listed. ``listed`` hears how many of how many lists are listed, as each one
    is. Slow, so no transaction stays open."""
    url = collection.sharing_url if lists_playlists(collection) else None
    action_of = _new_list_actions(collection)
    first = not collection.lists
    known = {
        playlist.ref: (playlist.url, playlist.enabled and playlist.status == ListStatus.KNOWN.value, playlist.source_key)
        for playlist in collection.lists
    }
    adds_outside = adds_outside_videos(collection)
    known_slugs = known_video_slugs(s, collection, also) if adds_outside else frozenset()
    s.rollback()
    playlists = None
    if url is not None:
        try:
            playlists = source.season_lists(url)
        except Exception as exc:
            logger.info("Could not list the playlists of %s: %s", url, exc)
    # Each list is read by its own Source, such as a Daily Wire show among YouTube playlists.
    wanted: dict[str, dict[str, str]] = {}
    for ref, (playlist_url, on, source_key) in known.items():
        if on:
            wanted.setdefault(source_key, {})[ref] = playlist_url
    for playlist in playlists or ():
        if playlist.ref not in known and _added(action_of(playlist), first=first):
            wanted.setdefault(source.id, {})[playlist.ref] = playlist.url
    items: dict[str, tuple[ItemRef, ...]] = {}
    outside: list[VideoDetails] = []
    sources: dict[str, str] = {}
    total = sum(len(urls) for urls in wanted.values())
    done = 0

    def one_more() -> None:
        nonlocal done
        done += 1
        if listed is not None:
            listed(done, total)

    for source_key, urls in wanted.items():
        reader = source if source_key == source.id else get_source(source_key)
        found = list_each(reader, urls, each=one_more)
        items.update(found)
        for details in _look_up_outside(reader, adds_outside, known_slugs, found):
            outside.append(details)
            sources[details.slug] = source_key
    return LinkListing(playlists, items, outside, sources)


def list_each(
    source: Source, urls: dict[str, str], each: Callable[[], None] | None = None,
) -> dict[str, tuple[ItemRef, ...]]:
    """The videos of each list, in its order, by the key it has in ``urls``. A list that could not be listed is left
    out. ``each`` hears of every list as it is done. Slow, so no transaction stays open."""

    def list_one(url: str) -> tuple[ItemRef, ...] | None:
        try:
            return source.list_items(url)
        except Exception as exc:
            logger.info("Could not list the playlist %s: %s", url, exc)
            return None

    # A channel can have hundreds of playlists, each a lookup of a second or more, so a few are listed at once. Each
    # runs in a copy of this context, which tells the Source's pacing whose requests they are.
    items: dict[str, tuple[ItemRef, ...]] = {}
    with ThreadPoolExecutor(max_workers=_LISTS_AT_ONCE, thread_name_prefix="list-items", **keep_call_options()) as pool:
        listed = {key: pool.submit(contextvars.copy_context().run, list_one, url) for key, url in urls.items()}
        for key, future in listed.items():
            if (found := future.result()) is not None:
                items[key] = found
            if each is not None:
                each()
    return items


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


def _added(action: NewLinkSeasonAction, *, first: bool) -> bool:
    """A new list is in the collection: the lists the channel had when the collection was set up are, but for a kind
    it skips; and later ones are when the collection adds them, as a season or as part of the collection."""
    return action in (NewLinkSeasonAction.ADD, NewLinkSeasonAction.CONTENTS) or (
        first and action is not NewLinkSeasonAction.IGNORE)


def save_lists(s: Session, collection: Collection, listing: LinkListing) -> list[CollectionList]:
    """Store the channel's playlists and what the seasons among them hold. A playlist the channel added since the
    collection was set up is a season, is left off, or waits for the user's choice, as the collection says. Returns
    the ones that wait. A playlist the Site no longer lists stays, with what it held.

    ``s`` is a write transaction's session."""
    known = {playlist.ref: playlist for playlist in collection.lists}
    first = not known
    action_of = _new_list_actions(collection)
    asked: list[CollectionList] = []
    for position, found in enumerate(listing.playlists or ()):
        playlist = known.get(found.ref)
        if playlist is None:
            # Each kind of list has its own setting, such as a SoundCloud artist's albums and their playlists.
            action = action_of(found)
            asks = not first and action is NewLinkSeasonAction.ASK
            playlist = CollectionList(
                ref=found.ref, source_key=collection.source_key, site_key=collection.site_key,
                url=found.url, title=found.title, image_path=found.image_url, item_count=found.item_count,
                type_key=found.type.key, site_position=position, enabled=_added(action, first=first),
                status=(ListStatus.NEW if asks else ListStatus.KNOWN).value,
                # One the collection takes as part of it adds its videos to the other seasons.
                as_season=action is not NewLinkSeasonAction.CONTENTS,
            )
            collection.lists.append(playlist)
            known[found.ref] = playlist
            if asks:
                asked.append(playlist)
            continue
        for name, value in (
            ("title", found.title), ("url", found.url), ("image_path", found.image_url), ("item_count", found.item_count),
            ("site_position", position), ("type_key", found.type.key),
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
    """The episode numbers each season of the collection already uses: by its episodes, and by a downloaded episode
    elsewhere that still has the season's number from before the seasons were numbered again, such as S01E02 in
    what is the third season now."""

    def __init__(self, state: SeasonsState):
        self._state = state
        self._taken: dict[int, set[int]] = {}

    def _of(self, season: SeasonDraft) -> set[int]:
        if season.id not in self._taken:
            prefix = f"ep.S{season.season_number:02d}E"
            taken = set()
            for episode in self._state.episodes.values():
                identifier = episode.episode_identifier or ""
                if episode.season_id == season.id or identifier.startswith(prefix):
                    number = identifier.rpartition("E")[2]
                    if number.isdigit():
                        taken.add(int(number))
            self._taken[season.id] = taken
        return self._taken[season.id]

    def take(self, season: SeasonDraft, wanted: int | None) -> int:
        """The Source's own episode number, unless the season already has an episode with it."""
        taken = self._of(season)
        number = wanted if wanted is not None and wanted not in taken else max(taken, default=0) + 1
        taken.add(number)
        return number


def _found_list_season(collection) -> SeasonDraft | None:
    """The one season of a collection made from one list, when it has it: its first season that is not a year's."""
    return next((
        season for season in sorted(collection.seasons, key=lambda season: season.index)
        if season.season_type == SeasonType.NORMAL.value and season_year(season) is None
    ), None)


class SeasonFinder:
    """Finds the collection's seasons per year and playlist seasons, makes them when it has none yet, and moves
    episodes between them, in the planner's copy of the collection."""

    def __init__(self, state: SeasonsState):
        self._state = state
        self._collection = collection = state.collection
        self._now = state.now
        # A Source's own season is found by its slug, a season per year by its year, which is its slug too.
        self._by_slug = {season.slug: season for season in collection.seasons}
        self._by_year = {season_year(season): season for season in collection.seasons if season_year(season) is not None}
        self.numbers = SeasonNumbers(state)
        self._loose_one = loose_season_on(collection)
        self._from_list = made_from_list(collection)
        self._one_list = list_in_one_season(collection)
        self._feeds = feed_seasons(collection)

    def _season_args(self, *, slug: str, name: str, number: int, origin: SeasonOrigin) -> dict:
        collection = self._collection
        if collection.custom_season_order:
            # The user's order stays: a new season goes last.
            number = max((x.season_number for x in collection.seasons if x.season_type == SeasonType.NORMAL.value), default=0) + 1
        season_type = season_type_from_name(name)
        return dict(
            slug=slug, name=name, number=0 if season_type is SeasonType.EXTRA else number, origin=origin.value,
            season_type=season_type.value,
        )

    def create(self, *, slug: str, name: str, number: int, origin: SeasonOrigin) -> SeasonDraft:
        season = self._state.make_season(**self._season_args(slug=slug, name=name, number=number, origin=origin))
        self._by_slug[season.slug] = season
        if season_year(season) is not None:
            self._by_year[season_year(season)] = season
        return season

    def by_slug(self, slug: str) -> SeasonDraft | None:
        season = self._by_slug.get(slug)
        return season if season is not None and season.id in self._state.seasons else None

    def _named_number(self) -> int:
        """The number a new named season gets: after the other named ones, below the seasons per year."""
        return max(
            (season.season_number for season in self._collection.seasons if 0 < season.season_number < _FIRST_YEAR),
            default=0,
        ) + 1

    def planned(self, episode: EpisodeDraft, belonging: Belonging) -> SeasonDraft:
        """The season ``_season_for`` puts the episode in, without making it: one that is not there yet comes as it
        would be made, apart from the planner's copy."""
        collection = self._collection
        if belonging.link is not None:
            season, new = self._state.season(belonging.link.season_id), lambda: self._list_new(belonging.link)
        elif belonging.feed is not None:
            season, new = self._state.season(feed_season_ids(collection).get(belonging.feed)), lambda: self._feed_new(belonging.feed)
        elif belonging.loose and self._from_list:
            season, new = _found_list_season(collection), self._list_own_new
        elif belonging.loose:
            season, new = next((season for season in collection.seasons if season.loose), None), self._loose_new
        else:
            year = (episode.published_date or self._now).year
            season, new = self._by_year.get(year), lambda: self._year_new(year)
            season = season if season is not None and season.id in self._state.seasons else None
        if season is not None:
            return season
        draft = self._state.season_draft(**self._season_args(**new()))
        draft.loose = belonging.loose and not self._from_list
        return draft

    def loose_season(self) -> SeasonDraft:
        """The one season of the videos in none of the playlists that are seasons, named as their Site calls it, such
        as Videos, or Singles for an artist. A collection made from one list has no playlists: its one season is the
        list's own."""
        if self._from_list:
            return self.list_own_season()
        season = next((season for season in self._collection.seasons if season.loose), None)
        if season is None:
            season = self.create(**self._loose_new())
            season.loose = True
        return season

    def _loose_new(self) -> dict:
        name = loose_season_name(self._collection)
        return dict(slug=name.lower(), name=name, number=self._named_number(), origin=SeasonOrigin.VODLOFT)

    def list_own_season(self) -> SeasonDraft:
        """The one season of a collection made from one list, named after it, as the collection is."""
        season = _found_list_season(self._collection)
        if season is None:
            season = self.create(**self._list_own_new())
        return season

    def _list_own_new(self) -> dict:
        title = self._collection.title
        return dict(slug=slugify(title) or "1", name=title, number=1, origin=SeasonOrigin.LIST)

    def home_season(self, published_at: datetime | None, tag: str | None = None) -> SeasonDraft:
        """Where a new video in no playlist goes: the season of its feed, by its episode ``tag``, when that feed is a
        season of its own; the one season of a collection made from one list, the one season of such videos, or its
        season per year."""
        if tag is not None and tag in self._feeds:
            return self.feed_season(self._feeds[tag])
        if self._one_list:
            return self.list_own_season()
        if self._loose_one:
            return self.loose_season()
        return self.year_season(published_at)

    def year_season(self, published_at: datetime | None) -> SeasonDraft:
        year = (published_at or self._now).year
        season = self._by_year.get(year)
        if season is None or season.id not in self._state.seasons:
            season = self.create(**self._year_new(year))
        return season

    @staticmethod
    def _year_new(year: int) -> dict:
        return dict(slug=str(year), name=str(year), number=year, origin=SeasonOrigin.VODLOFT)

    def list_season(self, playlist: ListDraft) -> SeasonDraft:
        """A playlist's season, made when the playlist gets its first video."""
        season = self._state.season(playlist.season_id)
        if season is None:
            season = self.create(**self._list_new(playlist))
            playlist.season_id = season.id
        return season

    def _list_new(self, playlist: ListDraft) -> dict:
        number = self._named_number()
        return dict(slug=slugify(playlist.title) or str(number), name=playlist.title, number=number, origin=SeasonOrigin.LIST)

    def feed_season(self, ref: str) -> SeasonDraft:
        """A feed's own season, named after the feed, such as Shorts, made when the feed gets its first video there. It
        may be a season the user put the feed together with."""
        collection = self._collection
        season = self._state.season(feed_season_ids(collection).get(ref))
        if season is None:
            season = self.create(**self._feed_new(ref))
            collection.feed_seasons = {**(collection.feed_seasons or {}), ref: season.id}
        return season

    def _feed_new(self, ref: str) -> dict:
        type_ = next(type_ for type_ in collection_site(self._collection).types_of(SectionKind.FEED) if type_.feed_ref == ref)
        number = self._named_number()
        return dict(slug=slugify(type_.title) or str(number), name=type_.title, number=number, origin=SeasonOrigin.VODLOFT)

    def own_season(self, name: str) -> SeasonDraft:
        """A season of its own, such as for a video split by chapter."""
        number = self._named_number()
        return self.create(slug=slugify(name) or str(number), name=name, number=number, origin=SeasonOrigin.VODLOFT)

    def move(self, episode: EpisodeDraft, season: SeasonDraft) -> None:
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

    link: ListDraft | None = None
    """The link season it belongs in, or None for the season of videos in no playlist."""
    loose: bool = False
    """With no playlist: the one season of videos in no playlist, rather than its season per year."""
    feed: str | None = None
    """The feed, by ref, whose own season it belongs in."""


class _ChannelSeat:
    """The channel season, as one of the places a video belongs in beside its lists' seasons."""

    title = ""

    def __init__(self, season_ids: set[int]):
        self._ids = season_ids

    def holds(self, season_id: int | None) -> bool:
        return season_id in self._ids


@dataclass(frozen=True)
class _FeedSeat:
    """A feed's own season, as one of the places a video of the feed belongs in beside its lists' seasons."""

    ref: str
    season_id: int | None

    def holds(self, season_id: int | None) -> bool:
        return self.season_id is not None and season_id == self.season_id


_Seat = ListDraft | _ChannelSeat | _FeedSeat


def _seat_holds(seat: _Seat, season_id: int | None) -> bool:
    if isinstance(seat, (_ChannelSeat, _FeedSeat)):
        return seat.holds(season_id)
    return seat.season_id is not None and seat.season_id == season_id


class _Places:
    """Where each of the collection's videos belongs: the season of the first playlist that has it, or, in a collection
    that repeats videos, of each one, or else the season of what is part of the collection, as the collection is set.
    A video of a feed that is a season of its own belongs in that feed's season, also when a list season has it, if
    the collection repeats videos; otherwise the list's season wins. A video of the channel's other feeds also belongs
    in the channel season when it holds everything from the channel. Only videos in such a season move: a Source's own
    season and a video split by chapter stay.

    A video has an episode for each season it belongs in. One more than that is an extra, which leaves the collection:
    such as when the collection stops repeating videos, or a list that is a season no longer has one of them."""

    def __init__(self, state: SeasonsState, left: frozenset[int] = frozenset()):
        self._state = state
        collection = state.collection
        on = link_seasons_on(collection)
        every = _every_holder(active_lists(state)) if on else {}
        self.holders = {slug: lists[0] for slug, lists in every.items()}
        self.repeats = repeats_videos(collection)
        self.every = every if self.repeats else {}
        playlist_ids = {playlist.season_id for playlist in collection.lists if playlist.season_id is not None}
        self.loose_one = loose_season_on(collection)
        # A collection that only holds its link seasons has no season of videos in none of them: those leave, but for
        # the videos of its lists that are part of it.
        self.only = holds_only_link_seasons(collection)
        self.parts = _part_slugs(collection) if self.only else frozenset()
        self.loose_ids = {season.id for season in collection.seasons if season.loose}
        self.channel = _ChannelSeat(self.loose_ids) if self.loose_one and holds_whole_channel(collection) else None
        # The feeds that are a season of their own, by their videos' episode tag, and those seasons.
        self.feeds = feed_seasons(collection)
        self.feed_ids = feed_season_ids(collection)
        year_ids = {season.id for season in collection.seasons if season_year(season) is not None}
        # A collection made from one list has no playlists: its videos are in the list's one season, or in a season
        # per upload year, as it is set.
        self.from_list = made_from_list(collection)
        if self.from_list:
            own = _found_list_season(collection)
            self.loose_ids = {own.id} if own is not None else set()
            self.loose_one = list_in_one_season(collection)
            self.channel = None
            self.feeds = {}
        # A season that its lists just left, for another list's season, empties too.
        self.movable = playlist_ids | self.loose_ids | year_ids | set(self.feed_ids.values()) | left
        self.anything = (on or self.loose_one or bool(playlist_ids) or bool(self.loose_ids) or self.from_list
                         or bool(self.feeds) or bool(self.feed_ids))
        self.extras: set[int] = set()
        """The ids of the episodes a video has beyond one for each season it belongs in."""
        self.missing: dict[str, list[_Seat]] = {}
        """The places whose season has no episode of a video yet, by the video's slug."""
        self._planned: dict[int, _Seat | None] = {}
        self._feed_of: dict[str, str | None] = {}
        """The collection's own videos, of its feeds, by slug: with the ref of their feed when it is a season of its
        own."""
        if self.anything and not self.from_list:
            # A collection made from one list has one place for each video, so nothing to plan.
            self._plan()

    def _feed_seat(self, ref: str) -> _FeedSeat:
        return _FeedSeat(ref, self.feed_ids.get(ref))

    def feed_of(self, episode: EpisodeDraft) -> str | None:
        """The feed whose own season the collection's own video belongs in, by ref, when its feed is one."""
        if episode.from_link_season:
            return None
        return self.feeds.get(episode_tag(episode))

    def seats(self, slug: str) -> list[_Seat]:
        """Every place the video belongs in: its feed's own season or the channel season first, for a video of the
        channel's feeds, then the seasons of its lists."""
        lists: list[_Seat] = list(self.every.get(slug) or ([self.holders[slug]] if slug in self.holders else []))
        if slug not in self._feed_of:
            return lists
        ref = self._feed_of[slug]
        if ref is not None:
            # Without repeating, a list that is a season wins over the feed's own season.
            return [self._feed_seat(ref), *lists] if self.repeats or not lists else lists
        if self.channel is not None:
            return [self.channel, *lists]
        return lists

    def _plan(self) -> None:
        """Give each video's episodes the seasons it belongs in: an episode in one of them stays there, and each other
        one goes to a season that has none of the video yet, or is an extra when there are none left."""
        placed: dict[str, list[tuple[int, int]]] = {}
        for episode in sorted(self._state.episodes.values(), key=lambda episode: episode.id):
            if episode.part_of is not None:
                continue
            if not episode.from_link_season:
                self._feed_of.setdefault(episode.source_slug, self.feeds.get(episode_tag(episode)))
            if episode.season_id in self.movable:
                placed.setdefault(episode.source_slug, []).append((episode.id, episode.season_id))
        downloaded = {episode.id for episode in self._state.episodes.values() if episode.has_files}
        for slug, episodes in placed.items():
            seats = self.seats(slug)
            if len(episodes) == 1 and len(seats) <= 1:
                continue
            # A downloaded episode goes first, so that an extra is one with nothing downloaded where there is one.
            episodes.sort(key=lambda episode: episode[0] not in downloaded)
            if not seats:
                # One season it belongs in: the first episode goes there.
                self.extras.update(episode_id for episode_id, _ in episodes[1:])
                continue
            open_seats, others = list(seats), []
            kept: list[tuple[int, _Seat]] = []
            for episode_id, season_id in episodes:
                seat = next((seat for seat in open_seats if _seat_holds(seat, season_id)), None)
                if seat is None:
                    others.append(episode_id)
                    continue
                open_seats.remove(seat)
                self._planned[episode_id] = None
                kept.append((episode_id, seat))
            for episode_id in others:
                if open_seats:
                    self._planned[episode_id] = open_seats.pop(0)
                    continue
                # No season left for it: a downloaded episode takes the place of one with nothing downloaded, which
                # is the extra instead, so no download is lost to a copy.
                swap = next((one for one in kept if one[0] not in downloaded), None) if episode_id in downloaded else None
                if swap is None:
                    self.extras.add(episode_id)
                    continue
                kept.remove(swap)
                self._planned.pop(swap[0])
                self.extras.add(swap[0])
                self._planned[episode_id] = swap[1]
            if open_seats:
                self.missing[slug] = open_seats

    def belonging(self, episode: EpisodeDraft) -> Belonging | None:
        """Where the episode belongs, when that is not where it is. None for an extra, which leaves instead."""
        if episode.part_of is not None or episode.season_id not in self.movable or episode.id in self.extras:
            return None
        if episode.id in self._planned:
            seat = self._planned[episode.id]
            if seat is None:
                return None
            if isinstance(seat, _ChannelSeat):
                return Belonging(loose=True)
            if isinstance(seat, _FeedSeat):
                return Belonging(feed=seat.ref)
            return Belonging(seat)
        holder = self.holders.get(episode.source_slug)
        feed = self.feed_of(episode)
        if feed is not None and (holder is None or self.repeats):
            # The feed's own season holds its videos.
            return None if self._feed_seat(feed).holds(episode.season_id) else Belonging(feed=feed)
        if self.channel is not None and feed is None and not episode.from_link_season:
            # The channel season holds every video of its feeds.
            return None if episode.season_id in self.loose_ids else Belonging(loose=True)
        if holder is not None:
            return None if holder.season_id is not None and holder.season_id == episode.season_id else Belonging(holder)
        if self.only and episode.source_slug not in self.parts:
            return None
        if self.loose_one:
            return None if episode.season_id in self.loose_ids else Belonging(loose=True)
        return None if episode.season_id not in self.loose_ids and season_is_year(self._state.season(episode.season_id)) else Belonging()


def _tag_of(identifier: str | None) -> str:
    """The tag of the feed that brought an episode, from its identifier, as ``episode_tag`` reads it."""
    tag = (identifier or MAIN_TAG).partition(".")[0]
    return MAIN_TAG if tag == "aux" else tag


def _part_slugs(collection) -> frozenset[str]:
    """The videos of the collection's lists that are part of it rather than a season of their own."""
    return frozenset(slug for playlist in lists_in(collection) if not playlist.as_season for slug in playlist.items)


def season_is_year(season) -> bool:
    return season is not None and season_year(season) is not None


def _files_move(
    state: SeasonsState, finder: SeasonFinder, files: FileMoves, episode: EpisodeDraft, belonging: Belonging,
) -> bool:
    """Whether moving the downloaded episode where it belongs moves its files: one of them gets another path there, also
    in a season that is not made yet."""
    season = finder.planned(episode, belonging)
    return bool(files.moving(episode, season, number_in(state, episode.episode_identifier, season)))


def _season_for(finder: SeasonFinder, episode: EpisodeDraft, belonging: Belonging) -> SeasonDraft:
    if belonging.link is not None:
        return finder.list_season(belonging.link)
    if belonging.feed is not None:
        return finder.feed_season(belonging.feed)
    return finder.loose_season() if belonging.loose else finder.year_season(episode.published_date)


def place(
    state: SeasonsState, *, with_files: bool | set[int] = False, by_user: bool = False, drop: bool = True,
    left: frozenset[int] = frozenset(),
) -> int:
    """Put each of the collection's videos where it belongs, in the planner's copy: in the season of the first
    playlist that has it, or in the season of videos in no playlist. A video with files stays where it is, unless
    ``with_files`` is True or holds its id. Returns how many moved. ``by_user`` says the user changed the playlists,
    so the videos that leave take their files with them. The videos that left the collection go, unless ``drop`` is
    False because the playlists are about to be listed again. ``left`` holds the seasons that the user took lists out
    of, whose videos move too."""
    places = _Places(state, left)
    if drop:
        # A season the lists just left is one its videos leave too, also the extra episodes there.
        _drop_outside(state, by_user=by_user, extras=places.extras)
    if not places.anything:
        return 0
    kept = set() if with_files is True else {
        episode.id for episode in state.episodes.values() if episode.has_files
    } - (with_files or set())
    finder = SeasonFinder(state)
    files = FileMoves(state) if kept else None
    moved = 0
    emptied: set[int] = set()
    for episode in state.in_index_order():
        if episode.part_of is not None:
            continue
        if (
            episode.from_link_season and episode.removed_from_source and episode.source_slug in places.holders
            and episode.id not in places.extras
        ):
            # A playlist that is a season lists it again, so it is back at its Site.
            episode.removed_from_source = False
        belonging = places.belonging(episode)
        if belonging is None:
            continue
        if episode.id in kept and _files_move(state, finder, files, episode, belonging):
            # Its files would move, which waits for the user.
            continue
        season = _season_for(finder, episode, belonging)
        if season.id != episode.season_id:
            emptied.add(episode.season_id)
            finder.move(episode, season)
            moved += 1
    if places.missing:
        _add_placements(state, finder, places.missing)
    state.drop_emptied(emptied)
    arrange(state)
    return moved


def place_in_link_seasons(
    s: Session, collection: Collection, *, with_files: bool | set[int] = False, now: datetime | None = None,
    by_user: bool = False, drop: bool = True, left: frozenset[int] = frozenset(),
) -> int:
    """``place`` for the collection as it is, saved.

    ``s`` is a write transaction's session."""
    state = load_state(s, collection, now)
    staying = {episode.id: episode.season_id for episode in state.episodes.values() if episode.has_files}
    moved = place(state, with_files=with_files, by_user=by_user, drop=drop, left=left)
    apply_state(s, state)
    _note_health(s, collection)
    s.flush()
    if with_files is not True:
        # Downloads that changed season while their files keep their paths: their metadata names the season. Their
        # files are renamed too, should a path have changed after all.
        changed = [
            episode_id for episode_id, season_id in staying.items()
            if episode_id in state.episodes and state.episodes[episode_id].season_id != season_id
        ]
        if changed:
            from backend.services.season_moves import queue_metadata_rewrite

            queue_metadata_rewrite(s, collection, changed)
    return moved


def _note_health(s: Session, collection: Collection) -> None:
    # The collection's health keeps what its placement leaves for the user, such as downloads to move.
    from backend.services.collection_health import note_collection_health

    note_collection_health(s, collection)


def _add_placements(state: SeasonsState, finder: SeasonFinder, missing: dict[str, list[_Seat]]) -> None:
    """Give each video an episode in the seasons of ``missing`` it has none in yet, copied from one it has, with files
    of its own, which its collection's Download Profiles download as for a new video. A video its Site no longer
    has gets none."""
    originals: dict[str, EpisodeDraft] = {}
    for episode in sorted(state.episodes.values(), key=lambda episode: episode.id):
        if episode.part_of is None and episode.source_slug in missing and not episode.removed_from_source and episode.id > 0:
            originals.setdefault(episode.source_slug, episode)
    identifiers = {episode.episode_identifier for episode in state.episodes.values()}
    index = state.next_index() - 1
    for slug, seats in missing.items():
        original = originals.get(slug)
        if original is None:
            continue
        for seat in seats:
            season = (finder.loose_season() if isinstance(seat, _ChannelSeat)
                      else finder.feed_season(seat.ref) if isinstance(seat, _FeedSeat) else finder.list_season(seat))
            index += 1
            identifier = _identifier_in(state.collection, season, original.episode_identifier, identifiers, finder.numbers)
            identifiers.add(identifier)
            state.add_episode(replace(
                original, id=state.new_id(), season_id=season.id, episode_identifier=identifier, index=index,
                removed_from_source=False, has_files=False, copy_of=original.id, record=None,
            ))


def _identifier_in(collection, season: SeasonDraft, identifier: str, identifiers: set[str], numbers: SeasonNumbers) -> str:
    """The identifier of a video's episode in another season: the next number in that season, or for a collection
    that numbers its episodes across seasons, the next one there. One by date shares its video's date, so it is
    auxiliary, as a second video of the same moment is."""
    from backend.services.episode_numbering import next_identifier

    tag = (identifier or "ep").partition(".")[0]
    if tag == "ep" and collection.episode_identifier == EpisodeIdentifier.SEASONAL.value:
        return f"ep.S{season.season_number:02d}E{numbers.take(season, None):02d}"
    if tag == "ep" and collection.episode_identifier == EpisodeIdentifier.DATE_BASED.value:
        tag = "aux"
    return next_identifier(identifiers, tag)


def channel_feeds(collection: Collection) -> list[SectionType]:
    """The feeds of a channel collection's channel, such as a YouTube channel's Videos, Shorts and Live, which it can
    take or leave. Empty for a collection of a list, and one that holds only what its lists have."""
    if collection.kind != CollectionKind.CHANNEL.value or collection.sharing_url is None or holds_only_link_seasons(collection):
        return []
    return list(collection_site(collection).types_of(SectionKind.FEED))


def feed_tags_off(collection) -> frozenset[str]:
    """The episode tags of the channel's feeds the collection does not take, such as YouTube's short when its Shorts
    are switched off. A tag another feed it takes gives too stays."""
    if collection.feeds is None:
        return frozenset()
    feeds = collection_site(collection).types_of(SectionKind.FEED)
    on = {type_.episode_tag for type_ in feeds if type_.feed_ref in collection.feeds}
    return frozenset(type_.episode_tag for type_ in feeds if type_.feed_ref not in collection.feeds) - on


def episode_tag(episode) -> str:
    """The tag of the feed that brought an episode, from its identifier: an auxiliary one, of a second video of the
    same moment, is a main one too."""
    return _tag_of(episode.episode_identifier)


def _from_feed_off(collection, episode, off: frozenset[str]) -> bool:
    return bool(off) and not episode.from_link_season and episode_tag(episode) in off


def leaving(state: SeasonsState, extras: set[int] | None = None) -> list[EpisodeDraft]:
    """The videos the collection added from its playlists that no playlist in it lists any more, or all of them when
    it no longer adds such videos, and the videos of a feed it no longer takes that no playlist in it keeps. They
    leave the collection, files and all. So does a video's extra episode (``extra_episodes``), one more than the
    seasons it belongs in."""
    collection = state.collection
    held = _holders(lists_in(collection)) if adds_outside_videos(collection) else {}
    off = feed_tags_off(collection)
    extras = extra_episodes(state) if extras is None else extras
    return [
        episode for episode in sorted(state.episodes.values(), key=lambda episode: episode.id)
        if episode.id in extras
        or (episode.from_link_season and episode.video_slug not in held)
        or (_from_feed_off(collection, episode, off) and episode.video_slug not in held)
    ]


def leaving_outside(s: Session, collection: Collection) -> list[Episode]:
    """``leaving`` for the collection as it is."""
    ids = [episode.id for episode in leaving(load_state(s, collection))]
    return list(s.scalars(select(Episode).where(Episode.id.in_(ids)).order_by(Episode.id))) if ids else []


def _kept_by_lists(state: SeasonsState) -> None:
    """A video of a feed the collection no longer takes that a playlist in it keeps is the playlist's from now on, so
    it leaves with the playlist."""
    collection = state.collection
    off = feed_tags_off(collection)
    if not off or not adds_outside_videos(collection):
        return
    held = _holders(lists_in(collection))
    for episode in state.episodes.values():
        if not episode.from_link_season and episode.video_slug in held and _from_feed_off(collection, episode, off):
            episode.from_link_season = True


def extra_episodes(state: SeasonsState) -> set[int]:
    """The ids of the episodes a video has in the collection beyond one in each season it belongs in, such as after
    the collection stopped repeating videos in each season. Their downloads stay until Home asked whether to keep
    them."""
    places = _Places(state)
    return places.extras if places.anything else set()


def outside_only_in(state: SeasonsState) -> dict[int, tuple[int, int]]:
    """For each playlist in the collection, how many of the videos the collection added from its playlists only it
    lists, and so would leave with it, and how many of those have files. By playlist id."""
    listed: dict[str, list[int]] = {}
    for playlist in lists_in(state.collection):
        for slug in dict.fromkeys(playlist.items):
            listed.setdefault(slug, []).append(playlist.id)
    counts: dict[int, tuple[int, int]] = {}
    for episode in state.episodes.values():
        if not episode.from_link_season:
            continue
        holding = listed.get(episode.video_slug, ())
        if len(holding) == 1:
            count, files = counts.get(holding[0], (0, 0))
            counts[holding[0]] = (count + 1, files + episode.has_files)
    return counts


def remove_left_episode(s: Session, episode: Episode) -> None:
    """Remove an episode that left its collection, with its download records, and its season when that holds nothing
    else. Its files are gone already.

    ``s`` is a write transaction's session."""
    state = load_state(s, episode.collection)
    state.remove_episode(state.episodes[episode.id])
    apply_state(s, state)


def held_back(episode: Episode) -> bool:
    """Whether a video that left its collection keeps its files for now: one of its downloads is kept, or waits for
    the user to say whether to keep it."""
    from backend.services.removed_downloads import awaits_keep_answer

    return any(
        download.kept or awaits_keep_answer(
            download, removed_from_source=episode.removed_from_source, removed_by_retention=episode.removed_by_retention,
        )
        for download in episode.downloads
    )


def _drop_outside(state: SeasonsState, *, by_user: bool = False, extras: set[int] | None = None) -> None:
    """Remove the videos that left the collection: at once when they have no files, and otherwise by a task that
    deletes their files first. A downloaded video only leaves with its files when the user's own change made it
    leave; one the creator took out of a playlist stays, and the Home page asks whether to keep it."""
    _kept_by_lists(state)
    extras = extra_episodes(state) if extras is None else extras
    for episode in leaving(state, extras):
        if not episode.has_files:
            state.remove_episode(episode)
            continue
        if not by_user:
            # As for a video its Site no longer has: the Home page asks whether to keep the files.
            episode.removed_from_source = True
        state.leaving[episode.id] = Leaving(episode, by_user)


def seasons_with_parts(state: SeasonsState) -> set[int]:
    """The seasons that hold the parts of a video split by chapter."""
    return {episode.season_id for episode in state.episodes.values() if episode.part_of is not None}


def season_removable(season, with_parts: set[int]) -> bool:
    """Whether the user can remove the season: one that VODLoft or the user made, whose videos go where the
    collection's settings put them, as new videos would. Not a season the Site has itself, such as a show's seasons,
    nor the season of extras or of a video split by chapter."""
    if season.season_type == SeasonType.EXTRA.value or season.id in with_parts:
        return False
    return season.origin != SeasonOrigin.SITE.value


def let_go_of_seasons(state: SeasonsState, season_ids: set[int]) -> dict[int, tuple[str, bool]]:
    """Make the seasons the user removes seasons of nothing: no list's, not the one of the videos in no list, no
    year's. Their videos then go where the collection's settings put them, into seasons made anew where needed, which
    take the removed seasons' slugs, so Download Profiles find them again. Returns what each season was, by id: its
    slug and whether it was the season of videos in no list."""
    collection = state.collection
    for playlist in collection.lists:
        if playlist.season_id in season_ids:
            playlist.season_id = None
    if any(season_id in season_ids for season_id in (collection.feed_seasons or {}).values()):
        collection.feed_seasons = {
            ref: None if season_id in season_ids else season_id for ref, season_id in collection.feed_seasons.items()
        }
    slugs: dict[int, tuple[str, bool]] = {}
    for season in collection.seasons:
        if season.id in season_ids:
            slugs[season.id] = (season.slug, season.loose)
            season.loose = False
            season.slug = f"removed-{season.id}"
    return slugs


def rehome_removed(state: SeasonsState, slugs: dict[int, tuple[str, bool]]) -> None:
    """Move what is still in the removed seasons where a new video would go, and remove the seasons. Run after the
    collection's videos were placed in its seasons. A season its settings put the videos back in, such as the one
    season of a collection made from one list, stays as it was."""
    finder = SeasonFinder(state)
    for episode in state.in_index_order():
        if episode.season_id in slugs:
            finder.move(episode, finder.home_season(episode.published_date))
    filled = {episode.season_id for episode in state.episodes.values()}
    for season_id, (slug, loose) in slugs.items():
        season = state.seasons.get(season_id)
        if season is None:
            continue
        if season_id in filled:
            season.slug, season.loose = slug, loose
        else:
            state.drop_season(season_id)
    arrange(state)


def belonging(state: SeasonsState, episode_id: int) -> Belonging | None:
    """Where the copy's episode belongs, when its collection's playlists put it in another season than the one it is
    in. None when it is where it belongs."""
    places = _Places(state)
    return places.belonging(state.episodes[episode_id]) if places.anything else None


def belongs_elsewhere(s: Session, episode: Episode) -> Belonging | None:
    """Where a video belongs now, when its collection's playlists put it in another season than the one it is in.
    None when it is where it belongs."""
    return belonging(load_state(s, episode.collection), episode.id)


def moved(state: SeasonsState) -> list[EpisodeDraft]:
    """The collection's videos that its playlists put in another season than the one they are in: downloaded ones,
    which wait for the user to move them, since moving renames their files. A download whose files keep their paths
    in the new season never waits: its episode moves like any other, and its files stay."""
    places = _Places(state)
    if not places.anything:
        return []
    finder = SeasonFinder(state)
    files = FileMoves(state)
    return [
        episode for episode in sorted(state.episodes.values(), key=lambda episode: episode.id)
        if episode.season_id in places.movable and (belonging := places.belonging(episode)) is not None
        and (not episode.has_files or _files_move(state, finder, files, episode, belonging))
    ]


def moved_episodes(s: Session, collection: Collection) -> list[Episode]:
    """``moved`` for the collection as it is."""
    ids = [episode.id for episode in moved(load_state(s, collection))]
    return list(s.scalars(select(Episode).where(Episode.id.in_(ids)).order_by(Episode.id))) if ids else []
