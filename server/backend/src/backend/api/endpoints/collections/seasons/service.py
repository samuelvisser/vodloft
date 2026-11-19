"""A collection's Seasons dialog."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.models.collection_seasons import (
    CollectionSeasonsAPIRead, CollectionSeasonsAPIUpdate, MovedEpisodesAPIRead, ReassignedEpisodesAPIRead,
)
from backend.db.models import Collection, CollectionList, CollectionListItem, Episode, Season
from backend.db.models import MediaDownloadBase
from backend.services.collections import reindex_collection
from backend.services.errors import ServiceError
from backend.utils.helpers import with_article
from backend.services.new_lists import checked_new_link_seasons
from backend.services.link_seasons import (
    collection_list_kinds, collection_new_lists,
    LinkListing, follows_creator, holds_only_link_seasons, is_season, leaving_outside, list_names, lists_playlists,
    offers_link_seasons, outside_only_in, place_in_link_seasons, save_lists, active_lists,
)
from backend.services.season_moves import queue_season_folder_moves
from backend.services.season_order import (
    arrange_seasons, link_first_videos, lists_by_season, match_seasons_of_downloaded, renumber_seasons,
)
from backend.services.source_requests import asking_source
from config.network import is_no_internet_error
from backend.types.collection_types import CollectionType
from backend.types.season_types import SeasonType
from backend.types.link_season_types import NewLinkSeasonAction, LinkSeasons, ListStatus, OutsideVideos
from sources import Feature, get_source


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

    def __getattr__(self, name):
        return getattr(self.season, name)


@dataclass(frozen=True)
class _Playlist:
    playlist: object
    first_video_at: object
    leaving_count: int
    leaving_with_files: int

    def __getattr__(self, name):
        return getattr(self.playlist, name)


@dataclass(frozen=True)
class _View:
    collection: Collection
    seasons: list
    link_seasons_offered: bool
    names: object
    music: bool
    playlists: list
    outside_count: int
    outside_with_files: int
    has_own_link: bool
    lists_playlists: bool
    links_only_offered: bool
    only_leaving_count: int
    only_leaving_with_files: int
    creator_slug: str | None
    creator_title: str | None
    new_lists: list

    def __getattr__(self, name):
        return getattr(self.collection, name)


def moved_view(s: Session, collection_slug: str) -> MovedEpisodesAPIRead:
    """The collection's episodes that belong in another season now. Reading only."""
    from backend.services.link_seasons import moved_episodes
    from backend.services.reassigned import reassigned_episodes

    collection = _collection(s, collection_slug)
    # A video its creator places in another collection is Reassigned, not Moved.
    reassigned = {item.episode.id for item in reassigned_episodes(s, collection)}
    return MovedEpisodesAPIRead(episode_slugs=[
        episode.slug for episode in moved_episodes(s, collection) if episode.id not in reassigned
    ])


def reassigned_view(s: Session, collection_slug: str) -> ReassignedEpisodesAPIRead:
    """The collection's downloaded videos that its creator places in another collection now. Reading only."""
    from backend.services.reassigned import reassigned_episodes

    return ReassignedEpisodesAPIRead.model_validate({"episodes": reassigned_episodes(s, _collection(s, collection_slug))})


def seasons_view(s: Session, collection_slug: str) -> CollectionSeasonsAPIRead:
    collection = _collection(s, collection_slug)
    counts = dict(s.execute(
        select(Episode.season_id, func.count()).where(Episode.collection_id == collection.id).group_by(Episode.season_id)
    ).all())
    by_season = {season_id: [link.title for link in links] for season_id, links in lists_by_season(s, collection).items()}
    firsts = link_first_videos(s, collection)
    never = datetime.max.replace(tzinfo=timezone.utc)
    music = collection.type == CollectionType.MUSIC.value
    # An artist's albums in the artist's order; playlists in the order they were started, as far as the videos tell:
    # YouTube does not say when a playlist was made.
    # Links the user added stay in the order they were added.
    playlists = sorted(collection.lists, key=lambda playlist: (
        (playlist.site_position,) if music else (
            firsts.get(playlist.id, never), playlist.site_position if playlist.added_by_user else -playlist.site_position,
        )
    ))
    leaving = outside_only_in(s, collection)
    outside = s.scalars(select(Episode.id).where(Episode.collection_id == collection.id, Episode.from_link_season)).all()
    with_files = set(s.scalars(select(MediaDownloadBase.media_item_id).where(MediaDownloadBase.media_item_id.in_(outside))))
    only_leaving = _left_by_only(s, collection)
    only_with_files = set(s.scalars(
        select(MediaDownloadBase.media_item_id).where(MediaDownloadBase.media_item_id.in_(only_leaving))
    )) if only_leaving else set()
    return CollectionSeasonsAPIRead.model_validate(_View(
        collection=collection,
        seasons=[
            _Season(season, counts.get(season.id, 0), by_season.get(season.id, []))
            for season in sorted(collection.seasons, key=lambda season: season.index)
        ],
        link_seasons_offered=offers_link_seasons(collection),
        names=list_names(collection),
        music=music,
        playlists=[_Playlist(playlist, firsts.get(playlist.id), *leaving.get(playlist.id, (0, 0))) for playlist in playlists],
        outside_count=len(outside), outside_with_files=len(with_files),
        has_own_link=collection.sharing_url is not None, lists_playlists=lists_playlists(collection),
        links_only_offered=get_source(collection.source_key).has(Feature.LINK_COLLECTIONS),
        only_leaving_count=len(only_leaving), only_leaving_with_files=len(only_with_files),
        creator_slug=collection.creator.slug if follows_creator(collection) else None,
        creator_title=collection.creator.title if follows_creator(collection) else None,
        new_lists=collection_new_lists(collection),
    ))


def _left_by_only(s: Session, collection: Collection) -> list[int]:
    """The videos that would leave the collection if it held only what its playlists that are seasons have now."""
    if holds_only_link_seasons(collection):
        return []
    held = set(s.scalars(
        select(CollectionListItem.source_slug).where(CollectionListItem.list_id.in_(
            [link.id for link in collection.lists if is_season(collection, link)]
        ))
    ))
    return [
        episode_id for episode_id, slug in s.execute(
            select(Episode.id, Episode.video_slug).where(Episode.collection_id == collection.id)
        )
        if slug not in held
    ]


def update_seasons(s: Session, collection_slug: str, body: CollectionSeasonsAPIUpdate) -> CollectionSeasonsAPIRead:
    """Rename and order the collection's seasons, and set how its creator's playlists are seasons. Videos without files
    move to where they belong now; the playlists are listed again when that changed.

    ``s`` is a write transaction's session."""
    collection = _collection(s, collection_slug)
    seasons = {season.id: season for season in collection.seasons}
    if sorted(change.id for change in body.seasons) != sorted(seasons):
        season = CollectionType(collection.type).season_word
        raise ServiceError(f"The {season}s must name each {season} of the collection exactly once", field="seasons")
    playlists = {playlist.id: playlist for playlist in collection.lists}
    lists = list_names(collection)
    unknown = [change.id for change in [*body.playlists] if change.id not in playlists]
    unknown += [link_id for link_id in body.removed_links if link_id not in playlists]
    if unknown:
        raise ServiceError(f"{collection.title} has no {lists.one} {unknown[0]}", field="playlists")
    if any(not playlists[link_id].added_by_user for link_id in body.removed_links):
        raise ServiceError(f"Only a link you added can be removed; switch {with_article(lists.one)} of the creator off instead", field="playlists")
    only = body.outside_videos == OutsideVideos.ONLY
    if only and body.link_seasons == LinkSeasons.OFF:
        raise ServiceError(
            f"A collection that holds only what its {lists.many} have needs its {lists.many} as "
            f"{CollectionType(collection.type).season_word}s", field="link_seasons",
        )
    if only and not get_source(collection.source_key).has(Feature.LINK_COLLECTIONS):
        raise ServiceError(f"This collection can't hold only what its {lists.many} have", field="outside_videos")
    if not only and collection.sharing_url is None:
        raise ServiceError(
            f"This collection has no link of its own, so it can only hold what its {lists.many} have", field="outside_videos",
        )
    if not only and any(link.added_by_user and link.id not in body.removed_links for link in playlists.values()):
        raise ServiceError(
            f"Remove the links you added first: only a collection that holds what its {lists.many} have can keep them",
            field="outside_videos",
        )
    if follows_creator(collection) and body.link_seasons == LinkSeasons.ALL:
        raise ServiceError(
            f"{collection.creator.title} decides which of its {lists.many} come in; switch them on or off here",
            field="link_seasons",
        )
    if body.link_seasons != LinkSeasons.OFF and not only and not lists_playlists(collection):
        raise ServiceError(
            f"Only a collection of a whole channel, on a site whose {lists.many} can be "
            f"{CollectionType(collection.type).season_word}s, can make them {CollectionType(collection.type).season_word}s",
            field="link_seasons",
        )
    shared_seasons = {playlist.season_id for playlist in playlists.values() if playlist.season_id is not None}
    stray = next((change for change in body.playlists if change.season_id is not None and change.season_id not in shared_seasons), None)
    if stray is not None:
        raise ServiceError(
            f"{playlists[stray.id].title} can only join {'an album' if collection.type == CollectionType.MUSIC.value else 'a season'} "
            "that holds one of the collection's lists", field="playlists",
        )
    for change in body.seasons:
        seasons[change.id].name = change.name.strip()
    was_seasons = {link.season_id for link in active_lists(s, collection) if link.season_id is not None}
    was_only = holds_only_link_seasons(collection)
    relist = (
        collection.link_seasons != body.link_seasons
        or any(playlists[change.id].enabled != change.enabled for change in body.playlists)
        or (collection.outside_videos != body.outside_videos and body.outside_videos in (OutsideVideos.ADD, OutsideVideos.ONLY))
    )
    # Once a collection holds only what its playlists have, every video it has came from them and leaves with them;
    # once it holds its own link's videos again, the ones it has are its own.
    if only != was_only:
        for episode in s.scalars(select(Episode).where(Episode.collection_id == collection.id)):
            episode.from_link_season = only
    for link_id in body.removed_links:
        s.delete(playlists.pop(link_id))
    collection.link_seasons = body.link_seasons
    collection.outside_videos = body.outside_videos
    if not follows_creator(collection):
        # A creator's own collection follows what the creator does with a new playlist.
        current = {setting.key: setting.action for setting in collection_new_lists(collection)}
        collection.new_lists = checked_new_link_seasons(
            collection_list_kinds(collection), {**current, **body.new_lists},
            collection.type == CollectionType.MUSIC.value,
        )
    collection.loose_videos = body.loose_videos
    collection.list_layout = body.list_layout
    regrouped = _regroup(playlists, seasons, body)
    for change in body.playlists:
        if change.id not in playlists:
            continue
        # Saving the dialog is the user's choice about a playlist that waited for one.
        playlists[change.id].enabled = change.enabled
        playlists[change.id].status = ListStatus.KNOWN.value
    s.flush()
    s.expire(collection, ["lists"])
    current = [season.id for season in sorted(collection.seasons, key=lambda season: season.index)]
    wanted = [change.id for change in body.seasons]
    if body.custom_season_order:
        if wanted != current or not collection.custom_season_order:
            collection.custom_season_order = True
            renumber_seasons(s, collection, [seasons[season_id] for season_id in wanted])
    elif collection.custom_season_order:
        collection.custom_season_order = False
        arrange_seasons(s, collection)
    # The downloaded videos of a playlist that stopped being a season go where they would go if they were new, files
    # and all; the ones that leave the collection are removed with their files.
    lost = (was_seasons - {link.season_id for link in active_lists(s, collection)}) | regrouped
    leaving = {episode.id for episode in leaving_outside(s, collection)}
    # A collection that now holds only what its playlists have keeps no season of videos in none of them, so its
    # downloaded videos there move to their playlist's season too.
    leaves = lost | ({season.id for season in collection.seasons if season.season_type != SeasonType.EXTRA.value} - {
        link.season_id for link in active_lists(s, collection)
    } if only and not was_only else set())
    moving = set(s.scalars(
        select(Episode.id).join(MediaDownloadBase, MediaDownloadBase.media_item_id == Episode.id)
        .where(Episode.collection_id == collection.id, Episode.season_id.in_(leaves))
    )) - leaving if leaves else set()
    # A collection that only holds its playlists from now on lists them again first, so they say what they have now
    # before a video leaves for not being in them.
    relisting = relist and body.link_seasons != LinkSeasons.OFF
    place_in_link_seasons(
        s, collection, with_files=moving, drop=not (only and not was_only), by_user=True, left=frozenset(regrouped),
    )
    if moving:
        match_seasons_of_downloaded(s, collection, moving)
        queue_season_folder_moves(s, collection, sorted(moving))
    if relisting:
        reindex_collection(s, collection)
    s.flush()
    s.refresh(collection)
    return seasons_view(s, collection_slug)


def _regroup(playlists: dict[int, CollectionList], seasons: dict[int, Season], body: CollectionSeasonsAPIUpdate) -> set[int]:
    """Put each list in the season the user chose: another list's, or one of its own, which a list that shared its
    season gets when its videos are next placed. Returns the seasons that a list left, whose videos move."""
    holders: dict[int, int] = {}
    for playlist in playlists.values():
        if playlist.season_id is not None:
            holders[playlist.season_id] = holders.get(playlist.season_id, 0) + 1
    left: set[int] = set()
    for change in body.playlists:
        playlist = playlists.get(change.id)
        if playlist is None or playlist.season_id == change.season_id:
            continue
        if change.season_id is None and holders.get(playlist.season_id, 0) <= 1:
            # It has a season of its own already.
            continue
        if playlist.season_id is not None:
            left.add(playlist.season_id)
        playlist.season = seasons[change.season_id] if change.season_id is not None else None
        if change.season_id is not None:
            left.add(change.season_id)
    return left


@dataclass(frozen=True)
class _Lookup:
    source_key: str
    url: str


def links_lookup(s: Session, collection_slug: str) -> _Lookup:
    """What listing the collection's playlists needs, read before the slow lookup."""
    collection = _collection(s, collection_slug)
    if not lists_playlists(collection):
        raise ServiceError(f"This collection's link is not a creator with {list_names(collection).many}", field="link_seasons")
    if follows_creator(collection):
        raise ServiceError(
            f"{collection.creator.title} looks for new {list_names(collection).many} itself: check the creator", field="link_seasons",
        )
    return _Lookup(collection.source_key, collection.sharing_url)


def look_up_links(lookup: _Lookup) -> LinkListing:
    """The creator's playlists, asked of its Source. Slow: call it outside a transaction."""
    with asking_source("Could not list the playlists"):
        return LinkListing(get_source(lookup.source_key).season_lists(lookup.url))


def save_listed_links(s: Session, collection_slug: str, listing: LinkListing) -> CollectionSeasonsAPIRead:
    """Store the playlists the creator has now, before the user picks which are seasons. A playlist listed for the
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


@dataclass(frozen=True)
class AddedLink:
    """A link the user adds, as its Source describes it."""

    ref: str
    url: str
    title: str
    image_url: str | None


def link_to_add(s: Session, collection_slug: str, url: str) -> _AddLookup:
    """What looking up a link the user adds needs, read before the slow lookup."""
    collection = _collection(s, collection_slug)
    if not holds_only_link_seasons(collection):
        raise ServiceError(
            f"Only a collection that holds only what its {list_names(collection).many} have can take links you add", field="url",
        )
    source = get_source(collection.source_key)
    if not source.handles(url):
        raise ServiceError(f"{source.name} can't read this link", field="url")
    return _AddLookup(collection.source_key, url.strip())


def look_up_added_link(lookup: _AddLookup) -> AddedLink:
    """A playlist, channel or video at the link, as its Source describes it. Slow: call it outside a transaction."""
    source = get_source(lookup.source_key)
    try:
        found = source.collection_details(lookup.url)
        return AddedLink(found.slug, found.url, found.title, found.image_url)
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
    return AddedLink(video.slug, video.url or lookup.url, video.title, video.image_url)


def save_added_link(s: Session, collection_slug: str, link: AddedLink) -> CollectionSeasonsAPIRead:
    """Make a link the user added one of the collection's link seasons, and list what it has.

    ``s`` is a write transaction's session."""
    collection = _collection(s, collection_slug)
    same = next((known for known in collection.lists if known.ref == link.ref or known.url == link.url), None)
    if same is not None:
        raise ServiceError(f"{collection.title} has {same.title} already", field="url")
    collection.lists.append(CollectionList(
        ref=link.ref, url=link.url, title=link.title, image_path=link.image_url, added_by_user=True, enabled=True,
        status=ListStatus.KNOWN.value,
        site_position=max((known.site_position for known in collection.lists), default=-1) + 1,
    ))
    s.flush()
    reindex_collection(s, collection)
    s.refresh(collection)
    return seasons_view(s, collection_slug)


__all__ = [
    "moved_view",
    "AddedLink", "CollectionNotFoundError", "link_to_add", "look_up_added_link", "look_up_links", "links_lookup",
    "save_added_link", "save_listed_links", "seasons_view", "update_seasons",
]
