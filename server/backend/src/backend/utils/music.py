"""An episode as a music track: the artist, the album its season stands for, and its place on that album."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Mapping

from sqlalchemy import func, inspect, select

from backend.utils.episode import EpisodeIdentifierInfo

if TYPE_CHECKING:
    from backend.db.models import Episode


@dataclass(frozen=True)
class MusicTrack:
    artist: str
    album: str
    track_number: int | None
    year: str
    track_count: int | None = None
    """How many tracks the album has, as VODLoft knows it."""


def collection_artist(collection) -> str:
    """Who a collection's music is by: its creator, else its author, else the collection itself."""
    creator = getattr(collection, "creator", None)
    return (creator.title if creator is not None else None) or collection.author_name or collection.title


@dataclass(frozen=True)
class AlbumPlace:
    """Where an episode sits among its season's episodes, which are an album's tracks."""
    position: int
    """Its place in index order, counted from 1."""
    track_count: int


def album_places(session, season_ids: Iterable[int]) -> dict[int, AlbumPlace]:
    """Every episode of the seasons by id, with its place on its album, in one query for all of them."""
    from backend.db.models import Episode

    season_ids = set(season_ids)
    if not season_ids:
        return {}
    by_season = {"partition_by": Episode.season_id}
    rows = session.execute(select(
        Episode.id,
        func.count(Episode.id).over(**by_season, order_by=Episode.index),
        func.count(Episode.id).over(**by_season),
    ).where(Episode.season_id.in_(season_ids)))
    return {id_: AlbumPlace(position, count) for id_, position, count in rows}


def music_track(episode: "Episode", places: Mapping[int, AlbumPlace] | None = None) -> MusicTrack:
    """The episode as a track. ``places`` are the album places of its collection's episodes, from ``album_places``,
    for whoever makes the tracks of many episodes; without them the episode's own season is looked up."""
    published = episode.published_date
    place = _album_place(episode, places)
    return MusicTrack(
        artist=collection_artist(episode.collection), album=_album(episode),
        track_number=_track_number(episode, place), year=str(published.year) if published else "",
        track_count=place.track_count if place is not None else None,
    )


def _album(episode: "Episode") -> str:
    """A named season, such as a playlist, an album or a video split by chapter, is the album. A season per year holds
    a feed's uploads, so the collection is the album then, as it is for specials, unless the user named it."""
    collection, season = episode.collection, episode.season
    if season is None or season.season_number == 0:
        return collection.title
    return collection.title if season.name == season.slug and season.slug.isdigit() else season.name


def _album_place(episode: "Episode", places: Mapping[int, AlbumPlace] | None) -> AlbumPlace | None:
    if episode.season is None:
        return None
    if places is None:
        state = inspect(episode, raiseerr=False)
        session = state.session if state is not None else None
        if session is None:
            return None
        places = album_places(session, (episode.season_id,))
    return places.get(episode.id)


def _track_number(episode: "Episode", place: AlbumPlace | None) -> int | None:
    """The episode's number in its season, or else its place among the season's episodes."""
    info = EpisodeIdentifierInfo.from_identifier(episode.episode_identifier)
    if (episode.episode_identifier or "").startswith("ep.S") and (info.episode_number or "").isdigit():
        return int(info.episode_number)
    return place.position if place is not None else None
