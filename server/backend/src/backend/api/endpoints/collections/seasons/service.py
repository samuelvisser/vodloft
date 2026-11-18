"""A collection's Seasons dialog."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.models.collection_seasons import CollectionSeasonsAPIRead, CollectionSeasonsAPIUpdate
from backend.db.models import Collection, Episode
from backend.db.models import MediaDownloadBase
from backend.services.collections import reindex_collection
from backend.services.errors import ServiceError
from backend.services.link_seasons import (
    LinkListing, leaving_outside, link_season_names, offers_link_seasons, outside_only_in, place_in_link_seasons,
    save_season_links, season_links,
)
from backend.services.season_moves import queue_season_folder_moves
from backend.services.season_order import arrange_seasons, link_first_videos, match_seasons_of_downloaded, renumber_seasons
from backend.services.source_requests import asking_source
from backend.types.collection_types import CollectionType
from backend.types.link_season_types import NewLinkSeasonAction, LinkSeasons, LinkSeasonStatus, OutsideVideos
from sources import get_source


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
    link_title: str | None

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

    def __getattr__(self, name):
        return getattr(self.collection, name)


def seasons_view(s: Session, collection_slug: str) -> CollectionSeasonsAPIRead:
    collection = _collection(s, collection_slug)
    counts = dict(s.execute(
        select(Episode.season_id, func.count()).where(Episode.collection_id == collection.id).group_by(Episode.season_id)
    ).all())
    by_season = {playlist.season_id: playlist.title for playlist in collection.season_links if playlist.season_id is not None}
    firsts = link_first_videos(s, collection)
    never = datetime.max.replace(tzinfo=timezone.utc)
    music = collection.type == CollectionType.MUSIC.value
    # An artist's albums in the artist's order; playlists in the order they were started, as far as the videos tell:
    # YouTube does not say when a playlist was made.
    playlists = sorted(collection.season_links, key=lambda playlist: (
        (playlist.site_position,) if music else (firsts.get(playlist.id, never), -playlist.site_position)
    ))
    leaving = outside_only_in(s, collection)
    outside = s.scalars(select(Episode.id).where(Episode.collection_id == collection.id, Episode.from_link_season)).all()
    with_files = set(s.scalars(select(MediaDownloadBase.media_item_id).where(MediaDownloadBase.media_item_id.in_(outside))))
    return CollectionSeasonsAPIRead.model_validate(_View(
        collection=collection,
        seasons=[
            _Season(season, counts.get(season.id, 0), by_season.get(season.id))
            for season in sorted(collection.seasons, key=lambda season: season.index)
        ],
        link_seasons_offered=offers_link_seasons(collection),
        names=link_season_names(collection),
        music=music,
        playlists=[_Playlist(playlist, firsts.get(playlist.id), *leaving.get(playlist.id, (0, 0))) for playlist in playlists],
        outside_count=len(outside), outside_with_files=len(with_files),
    ))


def update_seasons(s: Session, collection_slug: str, body: CollectionSeasonsAPIUpdate) -> CollectionSeasonsAPIRead:
    """Rename and order the collection's seasons, and set how its channel's playlists are seasons. Videos without files
    move to where they belong now; the playlists are listed again when that changed.

    ``s`` is a write transaction's session."""
    collection = _collection(s, collection_slug)
    seasons = {season.id: season for season in collection.seasons}
    if sorted(change.id for change in body.seasons) != sorted(seasons):
        raise ServiceError("The seasons must name each season of the collection exactly once", field="seasons")
    playlists = {playlist.id: playlist for playlist in collection.season_links}
    unknown = [change.id for change in body.playlists if change.id not in playlists]
    if unknown:
        raise ServiceError(f"{collection.title} has no playlist {unknown[0]}", field="playlists")
    if body.link_seasons != LinkSeasons.OFF and not offers_link_seasons(collection):
        raise ServiceError(
            "Only a collection of a whole channel, on a site whose playlists can be seasons, can make them seasons",
            field="link_seasons",
        )
    for change in body.seasons:
        seasons[change.id].name = change.name.strip()
    was_seasons = {link.season_id for link in season_links(s, collection) if link.season_id is not None}
    relist = (
        collection.link_seasons != body.link_seasons
        or any(playlists[change.id].enabled != change.enabled for change in body.playlists)
        or (collection.outside_videos != body.outside_videos and body.outside_videos == OutsideVideos.ADD)
    )
    collection.link_seasons = body.link_seasons
    collection.outside_videos = body.outside_videos
    collection.new_link_seasons = body.new_link_seasons
    collection.loose_videos = body.loose_videos
    for change in body.playlists:
        # Saving the dialog is the user's choice about a playlist that waited for one.
        playlists[change.id].enabled = change.enabled
        playlists[change.id].status = LinkSeasonStatus.KNOWN.value
    s.flush()
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
    lost = was_seasons - {link.season_id for link in season_links(s, collection)}
    leaving = {episode.id for episode in leaving_outside(s, collection)}
    moving = set(s.scalars(
        select(Episode.id).join(MediaDownloadBase, MediaDownloadBase.media_item_id == Episode.id)
        .where(Episode.collection_id == collection.id, Episode.season_id.in_(lost))
    )) - leaving if lost else set()
    place_in_link_seasons(s, collection, with_files=moving)
    if moving:
        match_seasons_of_downloaded(s, collection, moving)
        queue_season_folder_moves(s, collection, sorted(moving))
    if relist and body.link_seasons != LinkSeasons.OFF:
        reindex_collection(s, collection)
    s.flush()
    s.refresh(collection)
    return seasons_view(s, collection_slug)


@dataclass(frozen=True)
class _Lookup:
    source_key: str
    url: str


def links_lookup(s: Session, collection_slug: str) -> _Lookup:
    """What listing the collection's playlists needs, read before the slow lookup."""
    collection = _collection(s, collection_slug)
    if not offers_link_seasons(collection):
        raise ServiceError("This collection's playlists can't be seasons", field="link_seasons")
    return _Lookup(collection.source_key, collection.sharing_url)


def look_up_links(lookup: _Lookup) -> LinkListing:
    """The channel's playlists, asked of its Source. Slow: call it outside a transaction."""
    with asking_source("Could not list the playlists"):
        return LinkListing(get_source(lookup.source_key).season_lists(lookup.url))


def save_listed_links(s: Session, collection_slug: str, listing: LinkListing) -> CollectionSeasonsAPIRead:
    """Store the playlists the channel has now, before the user picks which are seasons. A playlist listed for the
    first time is on, as when the collection is set up.

    ``s`` is a write transaction's session."""
    collection = _collection(s, collection_slug)
    if collection.season_links:
        # A playlist found now waits for the user's choice in the dialog, whatever the collection does with new ones.
        action = collection.new_link_seasons
        collection.new_link_seasons = NewLinkSeasonAction.ADD.value
        save_season_links(s, collection, listing)
        collection.new_link_seasons = action
    else:
        save_season_links(s, collection, listing)
    s.flush()
    return seasons_view(s, collection_slug)


__all__ = [
    "CollectionNotFoundError", "look_up_links", "links_lookup", "save_listed_links",
    "seasons_view", "update_seasons",
]
