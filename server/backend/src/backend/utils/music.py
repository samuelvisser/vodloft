"""An episode as a music track: the artist, the album its season stands for, and its place on that album."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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


def music_track(episode: "Episode") -> MusicTrack:
    published = episode.published_date
    return MusicTrack(
        artist=collection_artist(episode.collection), album=_album(episode), track_number=_track_number(episode),
        year=str(published.year) if published else "", track_count=_track_count(episode),
    )


def _album(episode: "Episode") -> str:
    """A named season, such as a playlist, an album or a video split by chapter, is the album. A season per year holds
    a feed's uploads, so the collection is the album then, as it is for specials, unless the user named it."""
    collection, season = episode.collection, episode.season
    if season is None or season.season_number == 0:
        return collection.title
    return collection.title if season.name == season.slug and season.slug.isdigit() else season.name


def _track_number(episode: "Episode") -> int | None:
    """The episode's number in its season, or else its place among the season's episodes."""
    info = EpisodeIdentifierInfo.from_identifier(episode.episode_identifier)
    if (episode.episode_identifier or "").startswith("ep.S") and (info.episode_number or "").isdigit():
        return int(info.episode_number)
    state = inspect(episode, raiseerr=False)
    session = state.session if state is not None else None
    if episode.season is None or session is None or episode.index is None:
        return None
    from backend.db.models import Episode

    return session.scalar(
        select(func.count(Episode.id)).where(Episode.season_id == episode.season_id, Episode.index <= episode.index)
    ) or None


def _track_count(episode: "Episode") -> int | None:
    """How many episodes the episode's season has, which is the album's number of tracks."""
    state = inspect(episode, raiseerr=False)
    session = state.session if state is not None else None
    if episode.season is None or session is None:
        return None
    from backend.db.models import Episode

    return session.scalar(select(func.count(Episode.id)).where(Episode.season_id == episode.season_id)) or None
