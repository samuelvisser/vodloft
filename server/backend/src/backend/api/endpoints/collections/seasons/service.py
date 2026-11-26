"""A collection's Seasons dialog."""
from __future__ import annotations

from backend.utils.helpers import name_in_text
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.api.models.collection_seasons import (
    CollectionSeasonsAPIRead, CollectionSeasonsAPIUpdate, MovedEpisodesAPIRead, ReviewFilesAPIRead, ReviewVideosAPIRead,
    SeasonsListingsAPIIn, SeasonsPreviewAPIRead, SeasonsReviewAPIRead, WaitingSeasonAPIRead,
)
from backend.db.models import Collection, CollectionList, CollectionListItem, Episode, LocalMediaProfileBase, MediaDownloadBase
from backend.services.collections import reindex_collection
from backend.services.errors import ServiceError
from backend.services.new_lists import checked_new_link_seasons
from backend.services.collection_health import note_collection_health
from backend.services.episode_identification import collection_work, queue_renumber
from backend.services.list_previews import Listing, ListingState, ListToList
from backend.services.reconcile import list_labels, move_preview, moves_made
from backend.services.link_seasons import (
    adds_outside_videos, collection_list_kinds, collection_new_lists, feed_season_ids, held_back, leaving, lists_in, moved,
    place,
    LinkListing, holds_only_link_seasons, is_in, section_list_names,
    channel_season_offered, lists_playlists, loose_season_name, made_from_list, offers_link_seasons, outside_only_in, save_lists,
    active_lists, let_go_of_seasons, moved_episodes, rehome_removed, season_removable, seasons_with_parts,
)
from backend.services.season_state import CollectionDraft, EpisodeDraft, ListDraft, SeasonsState, apply_state, load_state
from backend.services.sites import collection_creator_names, collection_site, preferred_sources, site_record
from backend.services.move_causes import changed_settings, note_move_causes, settings_of
from backend.types.move_cause_types import MoveCauseOrigin
from backend.services.season_order import (
    arrange, link_first_videos, lists_by_season, match_downloaded, renumber_seasons, season_year,
)
from backend.services.source_requests import asking_source
from config.network import is_no_internet_error
from backend.types.collection_contracts import collection_contract
from backend.types.collection_types import EpisodeIdentifier
from backend.types.season_types import SeasonType
from backend.types.resource_names import OWN_LINK_NAMES
from backend.types.link_season_types import (
    CollectionKind, LooseVideos, NewLinkSeasonAction, LinkSeasons, ListStatus, OutsideVideos, RepeatVideos,
)
from backend.services.source_options import ytdlp_call_options
from sources import Feature, Names, SectionKind, get_source, sources_for


class CollectionNotFoundError(LookupError):
    pass


def _collection(s: Session, slug: str) -> Collection:
    collection = s.scalar(select(Collection).where(Collection.slug == slug))
    if collection is None:
        raise CollectionNotFoundError(f"Collection '{slug}' not found")
    return collection


@dataclass(frozen=True)
class _Season:
    season: object
    episode_count: int
    list_titles: list[str]
    removable: bool

    @property
    def year(self) -> int | None:
        return season_year(self.season)

    def __getattr__(self, name):
        return getattr(self.season, name)


@dataclass(frozen=True)
class _Playlist:
    playlist: object
    first_video_at: object
    leaving_count: int
    leaving_with_files: int

    @property
    def listed(self) -> bool:
        return bool(self.playlist.items)

    def __getattr__(self, name):
        return getattr(self.playlist, name)


@dataclass(frozen=True)
class _View:
    collection: Collection
    seasons: list
    link_seasons_offered: bool
    list_types: object
    section_list_names: Names
    creator_list_names: Names
    loose_season: str
    site_order: bool
    words: object
    creator_names: Names
    media_names: Names
    playlists: list
    outside_count: int
    outside_with_files: int
    has_own_link: bool
    lists_playlists: bool
    made_from_list: bool
    links_only_offered: bool
    only_leaving_count: int
    only_leaving_with_files: int
    new_lists: list
    repeated_count: int
    feeds: list
    channel_season_names: dict[str, str]
    channel_season_offered: bool
    channel_names: Names

    def __getattr__(self, name):
        return getattr(self.collection, name)


def moved_view(s: Session, collection_slug: str) -> MovedEpisodesAPIRead:
    """The collection's episodes that belong in another season now. Reading only."""
    collection = _collection(s, collection_slug)
    return MovedEpisodesAPIRead(episode_slugs=[episode.slug for episode in moved_episodes(s, collection)])


@dataclass(frozen=True)
class _Feed:
    type: object
    on: bool
    as_season: bool
    season_id: int | None

    @property
    def ref(self) -> str:
        return self.type.feed_ref

    @property
    def names(self) -> Names:
        return self.type.names


def _feeds(collection: Collection) -> list[_Feed]:
    """The feeds of the collection's channel, whether it takes each, and whether each is a season of its own. A
    collection that holds only what its lists have takes none of them."""
    only = holds_only_link_seasons(collection)
    seasons = feed_season_ids(collection)
    return [
        _Feed(
            type_, not only and (collection.feeds is None or type_.feed_ref in collection.feeds),
            type_.feed_ref in (collection.feed_seasons or {}), seasons.get(type_.feed_ref),
        )
        for type_ in _channel_feeds(collection)
    ]


def _channel_feeds(collection: Collection):
    """The feeds of a channel collection's channel, also while it holds only what its lists have, when it takes
    none of them."""
    if collection.kind != CollectionKind.CHANNEL.value or collection.sharing_url is None:
        return []
    return list(collection_site(collection).types_of(SectionKind.FEED))


def _channel_season_names(collection: Collection) -> dict[str, str]:
    """What the channel season is called when it holds the whole channel or what is in no list, such as Channel and
    Videos, by the ``loose_videos`` choice that has it hold that."""
    site = collection_site(collection)
    return {
        LooseVideos.EVERYTHING.value: site.channel_collection_names.singular.capitalize(),
        LooseVideos.ONE_SEASON.value: collection_contract(collection.type).loose_season_on(site),
    }


def seasons_view(s: Session, collection_slug: str) -> CollectionSeasonsAPIRead:
    return _view(load_state(s, _collection(s, collection_slug)))


def _seasons(state: SeasonsState) -> list[_Season]:
    """The collection's seasons in their order, with what each holds."""
    counts = Counter(episode.season_id for episode in state.episodes.values())
    by_season = {season_id: [link.title for link in links] for season_id, links in lists_by_season(state).items()}
    # A feed's own season holds the feed, such as Shorts, before the lists put together with it.
    for feed in _feeds(state.collection):
        if feed.season_id is not None and feed.on and feed.as_season:
            by_season[feed.season_id] = [feed.type.title, *by_season.get(feed.season_id, [])]
    with_parts = seasons_with_parts(state)
    return [
        _Season(season, counts.get(season.id, 0), by_season.get(season.id, []), season_removable(season, with_parts))
        for season in state.ordered_seasons()
    ]


def _view(state: SeasonsState) -> CollectionSeasonsAPIRead:
    collection = state.collection
    firsts = link_first_videos(state)
    never = datetime.max.replace(tzinfo=timezone.utc)
    contract = collection_contract(collection.type)
    # An artist's albums in the artist's order; playlists in the order they were started, as far as the videos tell:
    # YouTube does not say when a playlist was made.
    # Links the user added stay in the order they were added.
    playlists = sorted(collection.lists, key=lambda playlist: (
        (playlist.site_position,) if contract.site_order else (
            firsts.get(playlist.id, never), playlist.site_position if playlist.added_by_user else -playlist.site_position,
        )
    ))
    leaving = outside_only_in(state)
    outside = [episode for episode in state.episodes.values() if episode.from_link_season]
    only_leaving = _left_by_only(state)
    lists = section_list_names(collection)
    return CollectionSeasonsAPIRead.model_validate(_View(
        collection=collection,
        seasons=_seasons(state),
        link_seasons_offered=offers_link_seasons(collection),
        list_types=collection_site(collection).types_of(SectionKind.LIST), section_list_names=lists,
        # A collection without a link of its own has no creator's lists, only the links the user gave it.
        creator_list_names=(
            OWN_LINK_NAMES if collection.sharing_url is None else _creator_lists(collection_creator_names(collection), lists)
        ),
        loose_season=loose_season_name(collection), site_order=contract.site_order,
        # The dialog calls VODLoft's own seasons seasons, or what the collection's type calls them, such as albums,
        # never what its Site calls them, such as playlists: those are the creator's lists.
        words=contract.words_for(collection_site(collection).audio_only),
        creator_names=collection_creator_names(collection), media_names=contract.media_names_on(collection_site(collection)),
        playlists=[_Playlist(playlist, firsts.get(playlist.id), *leaving.get(playlist.id, (0, 0))) for playlist in playlists],
        outside_count=len(outside), outside_with_files=sum(episode.has_files for episode in outside),
        has_own_link=collection.sharing_url is not None, lists_playlists=lists_playlists(collection),
        made_from_list=made_from_list(collection),
        links_only_offered=get_source(collection.source_key).has(Feature.LINK_COLLECTIONS),
        only_leaving_count=len(only_leaving), only_leaving_with_files=sum(episode.has_files for episode in only_leaving),
        new_lists=collection_new_lists(collection),
        repeated_count=_repeated(state),
        feeds=_feeds(collection),
        channel_season_names=_channel_season_names(collection),
        channel_season_offered=channel_season_offered(collection),
        channel_names=collection_site(collection).channel_collection_names,
    ))


def _creator_lists(creator: Names, lists: Names) -> Names:
    """The Site's lists as the creator's, such as creator playlists or artist albums."""
    return Names(f"{creator.singular} {lists.singular}", f"{creator.singular} {lists.plural}", creator.article)


def _repeated(state: SeasonsState) -> int:
    """How many episodes the collection has of videos it has an episode of already, in another season: the ones that
    leave when it gives each video one season only."""
    counts = Counter(episode.source_slug for episode in state.episodes.values() if episode.part_of is None)
    return sum(count - 1 for count in counts.values())


def _left_by_only(state: SeasonsState) -> list[EpisodeDraft]:
    """The videos that would leave the collection if it held only what its playlists have now."""
    if holds_only_link_seasons(state.collection):
        return []
    return _in_no_list(state)


def _in_no_list(state: SeasonsState) -> list[EpisodeDraft]:
    """The collection's videos that none of its lists in it has, as VODLoft last listed them."""
    collection = state.collection
    held = {slug for link in collection.lists if is_in(collection, link) for slug in link.items}
    return [episode for episode in state.episodes.values() if episode.video_slug not in held]


@dataclass(frozen=True)
class _Planned:
    """What planning the dialog's settings leaves to do besides saving the copy."""

    moving: set[int]
    """The downloaded episodes whose files move into another season's folder."""
    relisting: bool
    """The lists are listed again, which may add and remove videos."""
    was_only: bool


@dataclass(frozen=True)
class Listed:
    """What the open dialog listed for its review (``list_previews``), which its save takes along: the videos of the
    collection's lists by id, and of the links the user adds by the link as they gave it."""

    lists: Mapping[int, tuple[str, ...]] = field(default_factory=dict)
    links: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    running: tuple[Listing, ...] = ()
    """The listings still running."""

    @classmethod
    def of(cls, found: Sequence[Listing]) -> "Listed":
        done = [listing for listing in found if listing.state is ListingState.LISTED]
        return cls(
            lists={listing.list_id: listing.slugs for listing in done if listing.list_id is not None},
            links={listing.link: listing.slugs for listing in done if listing.link is not None},
            running=tuple(listing for listing in found if listing.state is ListingState.LISTING),
        )


def update_seasons(
    s: Session, collection_slug: str, body: CollectionSeasonsAPIUpdate, added: Sequence[AddedLink] = (),
    listed: Listed = Listed(),
) -> CollectionSeasonsAPIRead:
    """Save the Seasons dialog as its review showed it (``review_seasons``): rename and order the collection's seasons,
    set which feeds of its channel it takes and how its lists are seasons, as ``plan_seasons_dialog`` plans it, and
    move the downloads that then belong in another season, which numbers its episodes again unless ``body`` says not
    to. ``added`` are the links the user adds, looked up before the transaction (see ``look_up_added_link``), and
    ``listed`` what the dialog listed for its review.

    ``s`` is a write transaction's session."""
    collection = _collection(s, collection_slug)
    # As the settings are before saving, for what the Move dialog shows changed.
    was_settings = settings_of(collection, MoveCauseOrigin.SEASONS)
    _check_added(collection, body, bool(added))
    _check_seasons(collection, body)
    links = [(link, _add_link(s, collection, link)) for link in added]
    s.flush()
    for playlist in collection.lists:
        if playlist.id in listed.lists:
            _store_items(s, playlist, listed.lists[playlist.id])
    for link, playlist in links:
        if playlist is not None and link.items:
            _store_items(s, playlist, link.items)
    s.flush()
    state = load_state(s, collection)
    before = {episode.id: episode.season_id for episode in state.episodes.values() if episode.has_files}
    planned = plan_seasons_dialog(state, body)
    # The user saw and agreed to what moves, so the downloads that belong in another season now move along.
    waiting = {episode.id for episode in moved(state)}
    if waiting:
        place(state, with_files=waiting, drop=False)
    done = moves_made(s, state, before, list_labels(state))
    apply_state(s, state)
    s.flush()
    again = EpisodeIdentifier(collection.episode_identifier) is not EpisodeIdentifier.DATE_BASED and body.renumber
    if done.renamed:
        # Numbers the episodes again, unless the user said not to, then moves each downloaded file to its season's
        # folder and its name.
        queue_renumber(s, collection, renumber=again)
    # A link the user added lists its videos, which then get its season.
    if (planned.relisting or bool(added)) and body.link_seasons != LinkSeasons.OFF:
        reindex_collection(s, collection, by_user=True)
    s.flush()
    note_collection_health(s, collection)
    note_move_causes(collection, MoveCauseOrigin.SEASONS, was_settings, waiting=bool(moved_episodes(s, collection)))
    s.flush()
    s.refresh(collection)
    return seasons_view(s, collection_slug)


def _check_added(collection: Collection, body: CollectionSeasonsAPIUpdate, adds: bool) -> None:
    if adds and body.link_seasons == LinkSeasons.OFF:
        raise ServiceError(
            f"Switch the {section_list_names(collection).plural} and links on to add links", field="link_seasons",
        )


def _store_items(s: Session, playlist: CollectionList, slugs: tuple[str, ...]) -> None:
    """What the dialog listed of the list, as listing the collection stores it."""
    s.execute(delete(CollectionListItem).where(CollectionListItem.list_id == playlist.id))
    s.add_all(CollectionListItem(list_id=playlist.id, source_slug=slug, position=position) for position, slug in enumerate(slugs))


def _check_seasons(collection: Collection, body: CollectionSeasonsAPIUpdate) -> None:
    if sorted(change.id for change in body.seasons) != sorted(season.id for season in collection.seasons):
        season = collection_contract(collection.type).words.season
        raise ServiceError(f"The {season.plural} must name each {season.singular} of the collection exactly once", field="seasons")


def plan_seasons_dialog(state: SeasonsState, body: CollectionSeasonsAPIUpdate) -> _Planned:
    """Plan saving the Seasons dialog with ``body`` on the planner's copy of the collection: its settings, the names
    and order of its seasons, and where its videos go. Videos without files move to where they belong now, and so do
    downloaded ones of a season that its lists left; the playlists are listed again when that changed."""
    collection = state.collection
    _check_seasons(collection, body)
    seasons = {season.id: season for season in collection.seasons}
    playlists = {playlist.id: playlist for playlist in collection.lists}
    lists = section_list_names(collection)
    unknown = [change.id for change in [*body.playlists] if change.id not in playlists]
    unknown += [link_id for link_id in body.removed_links if link_id not in playlists]
    if unknown:
        raise ServiceError(f"{name_in_text(collection.title)} has no {lists.singular} {unknown[0]}", field="playlists")
    if any(not playlists[link_id].added_by_user for link_id in body.removed_links):
        raise ServiceError(f"Only a link you added can be removed; switch {lists.a} of the channel off instead", field="playlists")
    only = body.outside_videos == OutsideVideos.ONLY
    if body.loose_videos == LooseVideos.EVERYTHING and collection.kind != CollectionKind.CHANNEL.value:
        raise ServiceError(
            f"Only a channel collection can keep every {collection_contract(collection.type).words.episode.singular} in "
            f"one {collection_contract(collection.type).words.season.singular}", field="loose_videos",
        )
    if only and body.link_seasons == LinkSeasons.OFF:
        raise ServiceError(
            f"A collection that holds only what its {lists.plural} have needs its {lists.plural} as "
            f"{collection_contract(collection.type).words.season.plural}", field="link_seasons",
        )
    if only and not get_source(collection.source_key).has(Feature.LINK_COLLECTIONS):
        raise ServiceError(f"This collection can't hold only what its {lists.plural} have", field="outside_videos")
    if not only and collection.sharing_url is None:
        raise ServiceError(
            f"This collection has no link of its own, so it can only hold what its {lists.plural} have", field="outside_videos",
        )
    feed_refs = [feed.ref for feed in _feeds(collection)]
    if body.feeds is not None and not set(body.feeds) <= set(feed_refs):
        raise ServiceError(f"{name_in_text(collection.title)} has no feed {sorted(set(body.feeds) - set(feed_refs))[0]}", field="feeds")
    # A collection that holds only what its lists have takes none of its channel's feeds.
    feeds = [] if only and feed_refs else (
        None if body.feeds is None or set(body.feeds) == set(feed_refs) else [ref for ref in feed_refs if ref in body.feeds]
    )
    if feeds == [] and not only and (body.outside_videos != OutsideVideos.ADD or body.link_seasons == LinkSeasons.OFF):
        raise ServiceError(
            f"A collection without feeds holds only what its {lists.plural} have: add their other videos too",
            field="feeds",
        )
    if body.link_seasons != LinkSeasons.OFF and not only and not lists_playlists(collection):
        raise ServiceError(
            f"Only a collection of a whole channel, on a site whose {lists.plural} can be "
            f"{collection_contract(collection.type).words.season.plural}, can make them "
            f"{collection_contract(collection.type).words.season.plural}",
            field="link_seasons",
        )
    # A list or feed can join a season another list or feed has.
    feed_seasons = feed_season_ids(collection)
    shared_seasons = {playlist.season_id for playlist in playlists.values() if playlist.season_id is not None} | set(feed_seasons.values())
    stray = next((change for change in body.playlists if change.season_id is not None and change.season_id not in shared_seasons), None)
    if stray is not None:
        raise ServiceError(
            f"{playlists[stray.id].title} can only join {collection_contract(collection.type).words.season.a} "
            "that holds one of the collection's lists or feeds", field="playlists",
        )
    wanted_feeds = dict(body.feed_seasons) if body.feed_seasons is not None else None
    if wanted_feeds is not None:
        taken = set(feed_refs if feeds is None else feeds)
        unknown_feed = sorted(set(wanted_feeds) - set(feed_refs))
        if unknown_feed:
            raise ServiceError(f"{name_in_text(collection.title)} has no feed {unknown_feed[0]}", field="feeds")
        # A feed the collection does not take is no season.
        wanted_feeds = {ref: target for ref, target in wanted_feeds.items() if ref in taken}
        stray_feed = next((ref for ref, target in wanted_feeds.items() if target is not None and target not in shared_seasons), None)
        if stray_feed is not None:
            raise ServiceError(
                f"A feed can only join {collection_contract(collection.type).words.season.a} that holds one of the "
                "collection's lists or feeds", field="feeds",
            )
    defaults = [change for change in body.playlists if change.is_default]
    if defaults and collection.sharing_url is not None:
        raise ServiceError(
            f"{name_in_text(collection.title)} has a link of its own, so none of its {lists.plural} is its default",
            field="playlists",
        )
    if len(defaults) > 1:
        raise ServiceError(f"Choose one {lists.singular} as the default", field="playlists")
    removed = set(body.removed_seasons)
    with_parts = seasons_with_parts(state)
    fixed = next((
        season for season_id, season in seasons.items() if season_id in removed and not season_removable(season, with_parts)
    ), None)
    if removed - set(seasons) or fixed is not None:
        raise ServiceError(
            f"{fixed.name if fixed is not None else 'That'} is not {collection_contract(collection.type).words.season.a} "
            "you can remove", field="seasons",
        )
    for change in body.seasons:
        seasons[change.id].name = change.name.strip()
    # Every season a list has, also one of a list that is not a season now, such as one the old creators left while
    # the collection's playlists were off: a season that no list holds after saving empties.
    was_seasons = {link.season_id for link in playlists.values() if link.season_id is not None} | set(feed_seasons.values())
    was_only = holds_only_link_seasons(collection)
    was_named = loose_season_name(collection)
    relist = (
        collection.feeds != feeds
        or collection.link_seasons != body.link_seasons
        or any(playlists[change.id].enabled != change.enabled for change in body.playlists)
        or (collection.outside_videos != body.outside_videos and body.outside_videos in (OutsideVideos.ADD, OutsideVideos.ONLY))
    )
    # Once a collection holds only what its playlists have, every video it has came from them and leaves with them;
    # once it holds its own link's videos again, the ones it has are its own.
    if only != was_only:
        for episode in state.episodes.values():
            episode.from_link_season = only
    for link_id in body.removed_links:
        state.drop_list(playlists.pop(link_id))
    collection.link_seasons = LinkSeasons(body.link_seasons).value
    collection.outside_videos = OutsideVideos(body.outside_videos).value
    collection.feeds = feeds
    current = {setting.key: setting.action for setting in collection_new_lists(collection)}
    collection.new_lists = checked_new_link_seasons(
        collection_list_kinds(collection), {**current, **body.new_lists},
        albums_only=collection_contract(collection.type).album_lists,
    )
    collection.loose_videos = LooseVideos(body.loose_videos).value
    if body.repeat_videos is not None:
        # An episode of a video in each season it belongs in, made or let go of below.
        collection.repeat_videos = RepeatVideos(body.repeat_videos).value
    regrouped = _regroup(playlists, body)
    if wanted_feeds is not None:
        regrouped |= _regroup_feeds(collection, playlists, wanted_feeds)
    for change in body.playlists:
        if change.id not in playlists:
            continue
        # Saving the dialog is the user's choice about a playlist that waited for one.
        playlists[change.id].enabled = change.enabled
        playlists[change.id].status = ListStatus.KNOWN.value
        playlists[change.id].as_season = change.as_season
        playlists[change.id].is_default = change.is_default
    # The channel season takes the name its new settings, and those of its lists, give it, such as Channel once it
    # holds everything, unless the user named it themselves.
    named = loose_season_name(collection)
    if named != was_named:
        for season in collection.seasons:
            if season.loose and season.name == was_named:
                season.name = named
    # Choosing another default, or removing it, leaves one default: the first link that stays, if the user chose none.
    collection.keep_a_default_link(playlists.values())
    removed_slugs = let_go_of_seasons(state, removed) if removed else {}
    current = [season.id for season in state.ordered_seasons()]
    wanted = [change.id for change in body.seasons]
    if body.custom_season_order:
        if wanted != current or not collection.custom_season_order:
            collection.custom_season_order = True
            renumber_seasons(state, [seasons[season_id] for season_id in wanted])
    elif collection.custom_season_order:
        collection.custom_season_order = False
        arrange(state)
    # The downloaded videos of a playlist that stopped being a season go where they would go if they were new, files
    # and all; the ones that leave the collection are removed with their files.
    lost = (was_seasons - {link.season_id for link in active_lists(state)} - set(feed_season_ids(collection).values())) | regrouped | removed
    going = {episode.id for episode in leaving(state)}
    # A collection that now holds only what its playlists have keeps no season of videos in none of them, so its
    # downloaded videos there move to their playlist's season too.
    leaves = lost | ({season.id for season in collection.seasons if season.season_type != SeasonType.EXTRA.value} - {
        link.season_id for link in active_lists(state)
    } if only and not was_only else set())
    moving = {
        episode.id for episode in state.episodes.values() if episode.has_files and episode.season_id in leaves
    } - going
    # A collection that only holds its playlists from now on lists them again first, so they say what they have now
    # before a video leaves for not being in them.
    place(state, with_files=moving, drop=not (only and not was_only), by_user=True, left=frozenset(regrouped | removed))
    if removed_slugs:
        rehome_removed(state, removed_slugs)
    if moving:
        match_downloaded(state, moving)
    return _Planned(moving=moving, relisting=relist and body.link_seasons != LinkSeasons.OFF, was_only=was_only)


@dataclass
class _Copy:
    """The planner's copy of the collection after planning the dialog's settings and what saving sets going."""

    state: SeasonsState
    was_settings: dict
    was_seasons: dict[int, str]
    """The collection's seasons before, by id, with their names."""
    downloaded: dict[int, int]
    """The episodes with files before, by id, with their seasons."""
    was_waiting: set[int]
    """The lists that waited to be listed for a season of their own already."""


def _plan_copy(s: Session, collection: Collection, body: CollectionSeasonsAPIUpdate, listed: Listed) -> _Copy:
    """Plan saving the dialog with ``body`` on the planner's copy of the collection, with what the dialog listed, and
    then what the save sets going: downloaded videos that leave are removed with their files by a task, a collection
    that now holds only what its lists have loses the videos in none of them once its lists are listed again, and the
    downloaded videos that belong in another season move. Saves nothing."""
    _check_added(collection, body, bool(body.added_links))
    was_settings = settings_of(collection, MoveCauseOrigin.SEASONS)
    state = load_state(s, collection)
    was_seasons = {season.id: season.name for season in state.seasons.values()}
    downloaded = {episode.id: episode.season_id for episode in state.episodes.values() if episode.has_files}
    was_waiting = {playlist.id for playlist in active_lists(state) if playlist.season_id not in state.seasons}
    for playlist in state.lists:
        if playlist.id in listed.lists:
            playlist.items = listed.lists[playlist.id]
    _add_drafts(s, collection, state, body, listed)
    planned = plan_seasons_dialog(state, body)
    gone = [
        episode for episode in leaving(state)
        if not episode.has_files or (episode.id in state.leaving and state.leaving[episode.id].by_user)
        or not held_back(s.get(Episode, episode.id))
    ]
    if holds_only_link_seasons(state.collection) and not planned.was_only:
        gone += _in_no_list(state)
    for episode in gone:
        if episode.id in state.episodes:
            state.remove_episode(episode)
    if gone:
        arrange(state)
    waiting = {episode.id for episode in moved(state)}
    if waiting:
        place(state, with_files=waiting, drop=False)
    return _Copy(state, was_settings, was_seasons, downloaded, was_waiting)


def _add_drafts(
    s: Session, collection: Collection, state: SeasonsState, body: CollectionSeasonsAPIUpdate, listed: Listed,
) -> None:
    """The links the user adds, as lists of the copy, with what the dialog listed of them."""
    position = max((known.site_position for known in collection.lists), default=-1) + 1
    for link in body.added_links:
        if any(known.url == link.url for known in collection.lists):
            continue
        source_key = link_to_add(s, collection.slug, link.url).source_key
        title = link.title or link.url
        # Never saved: the save adds the link as it looked it up.
        record = CollectionList(
            ref=link.url, url=link.url, title=title, source_key=source_key, added_by_user=True, enabled=True,
            status=ListStatus.KNOWN.value, as_season=link.as_season, is_default=False, site_position=position,
        )
        state.lists.append(ListDraft(
            record=record, id=state.new_id(), title=title, enabled=True, status=ListStatus.KNOWN.value,
            as_season=link.as_season, is_default=False, added_by_user=True, site_position=position, season_id=None,
            items=listed.links.get(link.url, ()),
        ))
        position += 1


def _waiting_seasons(state: SeasonsState) -> list[WaitingSeasonAPIRead]:
    # A list that is a season of its own but has none yet waits for VODLoft to list its videos.
    return [
        WaitingSeasonAPIRead(list_id=playlist.id, title=playlist.title)
        for playlist in active_lists(state) if playlist.season_id not in state.seasons
    ]


def preview_seasons(
    s: Session, collection_slug: str, body: CollectionSeasonsAPIUpdate, listed: Listed = Listed(),
) -> SeasonsPreviewAPIRead:
    """The seasons saving the dialog with ``body`` would leave, as the planner plans the save on its copy of the
    collection (``_plan_copy``): nothing is saved.

    Reading only."""
    state = _plan_copy(s, _collection(s, collection_slug), body, listed).state
    return SeasonsPreviewAPIRead(seasons=_seasons(state), waiting=_waiting_seasons(state))


# Videos the review names of each kind.
_EXAMPLES = 50


def review_seasons(
    s: Session, collection_slug: str, body: CollectionSeasonsAPIUpdate, listed: Listed = Listed(),
) -> SeasonsReviewAPIRead:
    """What saving the dialog with ``body`` does, for its review: the settings it changes, the seasons it makes and
    removes, the downloads it moves and the numbering after that, the videos that leave and the files deleted with
    them, and how many new videos join. Nothing is saved. While VODLoft works on the collection, or still lists a list
    the user switched on or a link they add, the review says what it waits for instead; downloads it does not wait
    for, as the new videos queue behind them.

    Reading only."""
    collection = _collection(s, collection_slug)
    work = collection_work(s, collection)
    if work is not None and not work.downloads:
        return SeasonsReviewAPIRead(busy=work.waiting())
    on = {change.id for change in body.playlists if change.enabled}
    titles = {playlist.id: playlist.title for playlist in collection.lists}
    asked = {link.url: link.title or link.url for link in body.added_links}
    still = [
        titles[listing.list_id] if listing.list_id is not None else asked[listing.link] for listing in listed.running
        if (listing.list_id in on and listing.list_id in titles) or listing.link in asked
    ]
    if still:
        return SeasonsReviewAPIRead(busy=(
            f"Listing the videos of {Names.joined([Names(name_in_text(title), name_in_text(title)) for title in still]).plural}, "
            "to show exactly what saving changes."
        ))
    copy = _plan_copy(s, collection, body, listed)
    state = copy.state
    done = moves_made(s, state, copy.downloaded, list_labels(state))
    moves = move_preview(s, collection, state, done)
    # An episode that goes while its video stays in another season, such as a list's copy of a video the collection
    # has elsewhere, is no video leaving the collection.
    staying = {episode.video_slug for episode in state.episodes.values()}
    gone = sorted(episode_id for episode_id, episode in state.gone.items() if episode.video_slug not in staying)
    extra = sorted(episode_id for episode_id, episode in state.gone.items() if episode.video_slug in staying)
    deleted = [episode_id for episode_id in sorted(state.gone) if episode_id in copy.downloaded]
    if adds_outside_videos(state.collection):
        known = {episode.video_slug for episode in [*state.episodes.values(), *state.gone.values()]}
        joining = len({slug for playlist in lists_in(state.collection) for slug in playlist.items} - known)
    else:
        joining = 0
    return SeasonsReviewAPIRead(
        seasons=_seasons(state), waiting=_waiting_seasons(state),
        causes=changed_settings(state.collection, MoveCauseOrigin.SEASONS, copy.was_settings),
        new_seasons=[
            *(season.name for season in state.ordered_seasons() if season.id < 0),
            *(waiting.title for waiting in _waiting_seasons(state) if waiting.list_id not in copy.was_waiting),
        ],
        deleted_seasons=[name for season_id, name in copy.was_seasons.items() if season_id not in state.seasons],
        moves=replace(moves, causes=[]),
        leaving=ReviewVideosAPIRead(count=len(gone), examples=_titles(s, gone)),
        extra=ReviewVideosAPIRead(count=len(extra), examples=_titles(s, extra)),
        deleted_files=ReviewFilesAPIRead(count=len(deleted), examples=_titles(s, deleted), profiles=_profiles(s, deleted)),
        joining=joining,
    )


def _titles(s: Session, episode_ids: list[int]) -> list[str]:
    """The episodes' titles, newest first, up to a few dozen."""
    if not episode_ids:
        return []
    return list(s.scalars(
        select(Episode.title).where(Episode.id.in_(episode_ids))
        .order_by(Episode.published_date.desc().nulls_last(), Episode.id.desc()).limit(_EXAMPLES)
    ))


def _profiles(s: Session, episode_ids: list[int]) -> list[str]:
    """The Local Media Profiles that have files of these episodes, by name."""
    if not episode_ids:
        return []
    return list(s.scalars(
        select(LocalMediaProfileBase.name).distinct()
        .join(MediaDownloadBase, MediaDownloadBase.local_media_profile_id == LocalMediaProfileBase.id)
        .where(MediaDownloadBase.media_item_id.in_(episode_ids)).order_by(LocalMediaProfileBase.name)
    ))


def lists_to_list(s: Session, collection_slug: str, body: SeasonsListingsAPIIn) -> list[ListToList]:
    """The lists the dialog asks to have listed for its review, with what listing each needs. Reading only."""
    collection = _collection(s, collection_slug)
    lists = {playlist.id: playlist for playlist in collection.lists}
    unknown = [list_id for list_id in body.list_ids if list_id not in lists]
    if unknown:
        raise ServiceError(
            f"{name_in_text(collection.title)} has no {section_list_names(collection).singular} {unknown[0]}", field="playlists",
        )
    options = tuple(collection.ytdlp_option_texts)
    wanted = [
        ListToList(lists[list_id].source_key, lists[list_id].url, options, list_id=list_id) for list_id in body.list_ids
    ]
    for link in body.links:
        lookup = link_to_add(s, collection_slug, link)
        wanted.append(ListToList(lookup.source_key, lookup.url, tuple(lookup.ytdlp_options), link=link))
    return wanted


def _regroup_feeds(collection: CollectionDraft, playlists: dict[int, ListDraft], wanted: dict[str, int | None]) -> set[int]:
    """Make the feeds in ``wanted`` the collection's feeds that are a season of their own, each in the season the user
    chose: another list's or feed's, or one of its own, which a feed that shared its season gets when its videos are
    next placed. Returns the seasons that a feed left or joined, whose videos move."""
    was = feed_season_ids(collection)
    holders: dict[int, int] = {}
    for season_id in [*(playlist.season_id for playlist in playlists.values()), *was.values()]:
        if season_id is not None:
            holders[season_id] = holders.get(season_id, 0) + 1
    left: set[int] = {season_id for ref, season_id in was.items() if ref not in wanted}
    chosen: dict[str, int | None] = {}
    for ref, target in wanted.items():
        current = was.get(ref)
        if target is None:
            # It keeps a season it has alone, and gets one of its own when it shared one.
            chosen[ref] = current if current is not None and holders.get(current, 0) <= 1 else None
        else:
            chosen[ref] = target
        if chosen[ref] != current:
            left |= {season_id for season_id in (current, chosen[ref]) if season_id is not None}
    collection.feed_seasons = chosen
    return left


def _regroup(playlists: dict[int, ListDraft], body: CollectionSeasonsAPIUpdate) -> set[int]:
    """Put each list in the season the user chose: another list's, or one of its own, which a list that shared its
    season gets when its videos are next placed. Returns the seasons that a list left, whose videos move."""
    holders: dict[int, int] = {}
    for playlist in playlists.values():
        if playlist.season_id is not None:
            holders[playlist.season_id] = holders.get(playlist.season_id, 0) + 1
    left: set[int] = set()
    for change in body.playlists:
        playlist = playlists.get(change.id)
        if playlist is None or playlist.season_id == change.season_id or not change.as_season:
            # A list without a season of its own keeps where its season was until it is a season again.
            continue
        if change.season_id is None and holders.get(playlist.season_id, 0) <= 1:
            # It has a season of its own already.
            continue
        if playlist.season_id is not None:
            left.add(playlist.season_id)
        playlist.season_id = change.season_id
        if change.season_id is not None:
            left.add(change.season_id)
    return left


@dataclass(frozen=True)
class _Lookup:
    source_key: str
    url: str
    ytdlp_options: tuple[str, ...] = ()


def links_lookup(s: Session, collection_slug: str) -> _Lookup:
    """What listing the collection's playlists needs, read before the slow lookup."""
    collection = _collection(s, collection_slug)
    if not lists_playlists(collection):
        raise ServiceError(f"This collection's link is not a channel with {section_list_names(collection).plural}", field="link_seasons")
    return _Lookup(collection.source_key, collection.sharing_url, collection.ytdlp_option_texts)


def look_up_links(lookup: _Lookup) -> LinkListing:
    """The channel's playlists, asked of its Source. Slow: call it outside a transaction."""
    with asking_source("Could not list the playlists"), ytdlp_call_options(lookup.source_key, *lookup.ytdlp_options):
        return LinkListing(get_source(lookup.source_key).season_lists(lookup.url))


def save_listed_links(s: Session, collection_slug: str, listing: LinkListing) -> CollectionSeasonsAPIRead:
    """Store the playlists the channel has now, before the user picks which are seasons. A playlist listed for the
    first time is on, as when the collection is set up.

    ``s`` is a write transaction's session."""
    collection = _collection(s, collection_slug)
    if collection.lists:
        # A playlist found now waits for the user's choice in the dialog, whatever the collection does with new ones.
        settings = collection.new_lists
        collection.new_lists = {setting.key: NewLinkSeasonAction.ADD.value for setting in collection_new_lists(collection)}
        save_lists(s, collection, listing)
        collection.new_lists = settings
    else:
        save_lists(s, collection, listing)
    s.flush()
    return seasons_view(s, collection_slug)




@dataclass(frozen=True)
class _AddLookup:
    source_key: str
    url: str
    ytdlp_options: tuple[str, ...] = ()


@dataclass(frozen=True)
class AddedLink:
    """A link the user adds, as its Source describes it."""

    ref: str
    url: str
    title: str
    image_url: str | None
    source_key: str
    as_season: bool = True
    """A season of its own; otherwise its videos are part of the collection."""
    items: tuple[str, ...] = ()
    """Its videos, as the dialog listed them for its review."""


def link_to_add(s: Session, collection_slug: str, url: str) -> _AddLookup:
    """What looking up a link the user adds needs, read before the slow lookup."""
    collection = _collection(s, collection_slug)
    # The collection may hold only what its lists have from this save on; saving checks that it does.
    if not get_source(collection.source_key).has(Feature.LINK_COLLECTIONS):
        raise ServiceError(f"{name_in_text(collection.title)} can't take links you add", field="url")
    url = url.strip()
    # The Source the user asks first for the link's Site reads it, which may be another one than the collection's.
    source = next((source for source in sources_for(url, preferred_sources(s)) if source.has(Feature.EPISODE_LISTS)), None)
    if source is None:
        raise ServiceError("VODLoft can't read this link", field="url")
    return _AddLookup(source.id, url, collection.ytdlp_option_texts)


def look_up_added_link(lookup: _AddLookup) -> AddedLink:
    """A playlist, channel or video at the link, as its Source describes it. Slow: call it outside a transaction."""
    with ytdlp_call_options(lookup.source_key, *lookup.ytdlp_options):
        return _look_up_added_link(lookup)


def _look_up_added_link(lookup: _AddLookup) -> AddedLink:
    source = get_source(lookup.source_key)
    try:
        found = source.collection_details(lookup.url)
        return AddedLink(found.slug, found.url, found.title, found.image_url, source.id)
    except Exception as exc:
        if is_no_internet_error(exc):
            raise
        listing_failed = exc
    try:
        # A link to one video is a season of one video.
        video = source.video_details(lookup.url)
    except Exception as exc:
        if is_no_internet_error(exc):
            raise
        raise ServiceError(f"{source.name} could not read this link: {listing_failed}", field="url") from exc
    return AddedLink(video.slug, video.url or lookup.url, video.title, video.image_url, source.id)


def _known_link(collection: Collection, link: AddedLink) -> CollectionList | None:
    return next((known for known in collection.lists if known.ref == link.ref or known.url == link.url), None)


def check_added_link(s: Session, collection_slug: str, link: AddedLink) -> AddedLink:
    """A link the user adds, unless the collection has it already."""
    collection = _collection(s, collection_slug)
    if (same := _known_link(collection, link)) is not None:
        raise ServiceError(f"{name_in_text(collection.title)} has {name_in_text(same.title)} already", field="url")
    return link


def _add_link(s: Session, collection: Collection, link: AddedLink) -> CollectionList | None:
    """Make a link the user added one of the collection's link seasons, or part of the collection. A link it has
    already stays as it is: returns None then."""
    if _known_link(collection, link) is not None:
        return None
    site = get_source(link.source_key).site_for(link.url)
    playlist = CollectionList(
        ref=link.ref, url=link.url, title=link.title, image_path=link.image_url, added_by_user=True, enabled=True,
        status=ListStatus.KNOWN.value, source_key=link.source_key, as_season=link.as_season,
        site_key=site_record(s, site).key if site is not None else None,
        site_position=max((known.site_position for known in collection.lists), default=-1) + 1,
    )
    collection.lists.append(playlist)
    collection.keep_a_default_link()
    return playlist


__all__ = [
    "moved_view",
    "AddedLink", "CollectionNotFoundError", "Listed", "lists_to_list", "preview_seasons", "review_seasons", "link_to_add", "look_up_added_link", "look_up_links", "links_lookup",
    "check_added_link", "save_listed_links", "seasons_view", "update_seasons",
]
