"""The order and numbers of a collection's seasons.

Seasons are numbered in the order they are shown. A collection with a season per upload year numbers those by
the year, until a playlist that is a season, or the user, puts seasons in between: from then on its seasons are
numbered 1, 2, 3 in the order they are shown. Once the user put them in their own order, a new season goes last,
with the next number. Without the user's own order, a playlist's season comes right after
the season of the year of its first video, so a playlist started in 2025 follows the 2025 season, and an artist's
albums follow the order the artist lists them in at the Site.

A season that gets another number takes its episodes without files along: S2024E03 becomes S03E03. An episode
with files keeps its identifier, so file names never change.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Collection, CollectionList, CollectionListItem, Episode, MediaDownloadBase, Season
from backend.types.collection_contracts import collection_contract
from backend.types.collection_types import EpisodeIdentifier
from backend.types.season_types import SeasonType

_SEASONAL = re.compile(r"^ep\.S(\d+)E(\d+)$")
_LAST = datetime.max.replace(tzinfo=timezone.utc)


def season_year(season: Season) -> int | None:
    """The upload year of a season per year. Found by its slug, which stays when the user renames the season."""
    return int(season.slug) if len(season.slug) == 4 and season.slug.isdigit() else None


def link_first_videos(s: Session, collection: Collection) -> dict[int, datetime]:
    """When the first video of the collection that each playlist has came out, by playlist id. YouTube does not say
    when a playlist was made, so this stands in for it."""
    # The lists are named by a subquery, so that SQLite starts from their videos rather than trying each of the
    # collection's episodes against each of its lists.
    rows = s.execute(
        select(CollectionListItem.list_id, func.min(Episode.published_date))
        .join(Episode, (Episode.collection_id == collection.id) & (Episode.source_slug == CollectionListItem.source_slug))
        .where(CollectionListItem.list_id.in_(select(CollectionList.id).where(CollectionList.collection_id == collection.id)))
        .group_by(CollectionListItem.list_id)
    )
    return {playlist_id: _aware(first) for playlist_id, first in rows if first is not None}


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _dated_order(s: Session, collection: Collection) -> list[Season]:
    """Seasons per year by their year, every other season right after the year it started in. In a Music collection
    the albums come after those, in the artist's order."""
    by_playlist = link_first_videos(s, collection)
    # A season of several lists starts with the first of them.
    playlist_starts: dict[int, datetime] = {}
    for playlist in collection.lists:
        if playlist.season_id is not None and playlist.id in by_playlist:
            start = by_playlist[playlist.id]
            playlist_starts[playlist.season_id] = min(start, playlist_starts.get(playlist.season_id, start))
    firsts = dict(s.execute(
        select(Episode.season_id, func.min(Episode.published_date))
        .where(Episode.collection_id == collection.id).group_by(Episode.season_id)
    ).all())

    # An artist's albums follow the order the artist gives them at the Site, after the singles.
    site_order = collection_contract(collection.type).site_order
    album_places: dict[int, int] = {}
    for link in collection.lists if site_order else ():
        if link.season_id is not None:
            album_places[link.season_id] = min(link.site_position, album_places.get(link.season_id, link.site_position))

    def key(season: Season):
        if season.season_type == SeasonType.EXTRA.value:
            return (2, 0, 0, _LAST, season.index)
        if season.loose:
            # The videos in no playlist come first, as a channel's Videos do.
            return (-1, 0, 0, _LAST, season.index)
        if season.id in album_places:
            return (1, album_places[season.id], 0, _LAST, season.index)
        year = season_year(season)
        if year is not None:
            return (0, year, 0, _LAST, season.index)
        start = playlist_starts.get(season.id) or (_aware(firsts[season.id]) if firsts.get(season.id) else None)
        start = start or _aware(season.created_at or datetime.now(timezone.utc))
        if site_order:
            # Another album, such as one split from a video by its chapters, after the artist's own, by date.
            return (1, len(album_places), 1, start, season.index)
        return (0, start.year, 1, start, season.index)

    return sorted(collection.seasons, key=key)


def arrange_seasons(s: Session, collection: Collection) -> None:
    """Put the collection's seasons in order after seasons were added or videos moved.

    ``s`` is a write transaction's session."""
    seasons = list(collection.seasons)
    if collection.custom_season_order:
        # A new season was made last, with the next number, so the user's order and numbers stay.
        _set_indices(s, sorted(seasons, key=lambda season: season.index))
    elif any(playlist.season_id is not None for playlist in collection.lists) or any(season.loose for season in seasons):
        renumber_seasons(s, collection, _dated_order(s, collection))
    else:
        _set_indices(s, sorted(seasons, key=lambda season: season.season_number))
    number_in_link_order(s, collection)


def lists_by_season(s: Session, collection: Collection) -> dict[int, list[CollectionList]]:
    """The lists of each season that has some, in the order its videos go: the list whose first video came out first
    comes first, so a "Part 1" playlist comes before "Part 2"."""
    firsts = link_first_videos(s, collection)
    by_season: dict[int, list[CollectionList]] = {}
    for link in collection.lists:
        if link.season_id is not None:
            by_season.setdefault(link.season_id, []).append(link)
    for links in by_season.values():
        links.sort(key=lambda link: (firsts.get(link.id, _LAST), link.site_position, link.id))
    return by_season


def number_in_link_order(s: Session, collection: Collection) -> None:
    """Number the episodes of each season of lists in the order its Site lists them, as a playlist or an album's
    tracks are, so S03E01 is the playlist's first video. A season of several lists has the videos of its first list
    first, then those of the next. An episode with files keeps its number, and the others go around it.

    ``s`` is a write transaction's session."""
    if collection.episode_identifier != EpisodeIdentifier.SEASONAL.value:
        return
    with_files = _with_files(s, collection)
    link_season_ids = {link.season_id for link in collection.lists if link.season_id is not None}
    # The identifiers that stay: of episodes with files, and of episodes in no link season.
    taken = set(s.scalars(select(Episode.episode_identifier).where(
        Episode.collection_id == collection.id,
        Episode.id.in_(with_files) | Episode.season_id.not_in(link_season_ids) | Episode.part_of.is_not(None),
    )))
    wanted: dict[int, str] = {}
    episodes: list[Episode] = []
    seasons = {season.id: season for season in collection.seasons}
    for season_id, links in lists_by_season(s, collection).items():
        season = seasons.get(season_id)
        if season is None:
            continue
        places: dict[str, tuple[int, int]] = {}
        for order, link in enumerate(links):
            for slug, position in s.execute(
                select(CollectionListItem.source_slug, CollectionListItem.position).where(CollectionListItem.list_id == link.id)
            ):
                places.setdefault(slug, (order, position))
        unplaced = (len(links), 0)
        rows = sorted(
            s.scalars(select(Episode).where(Episode.season_id == season.id, Episode.part_of.is_(None))),
            key=lambda episode: (places.get(episode.source_slug, unplaced), episode.index),
        )
        number = 0
        for episode in rows:
            if episode.id in with_files or not _SEASONAL.match(episode.episode_identifier or ""):
                continue
            number += 1
            while (identifier := f"ep.S{season.season_number:02d}E{number:02d}") in taken:
                number += 1
            taken.add(identifier)
            if episode.episode_identifier != identifier:
                wanted[episode.id] = identifier
                episodes.append(episode)
    _assign(s, episodes, wanted)


def _set_indices(s: Session, ordered: list[Season]) -> None:
    if [season.index for season in ordered] == list(range(1, len(ordered) + 1)):
        return
    # Two passes, because (collection_id, index) is unique.
    for offset, season in enumerate(ordered, start=1):
        season.index = -offset
    s.flush()
    for offset, season in enumerate(ordered, start=1):
        season.index = offset
    s.flush()


def renumber_seasons(s: Session, collection: Collection, ordered: list[Season]) -> None:
    """Show the seasons in this order and number them 1, 2, 3 in it. Extras stay season 0.

    ``s`` is a write transaction's session."""
    _set_indices(s, ordered)
    numbers: dict[int, int] = {}
    number = 0
    for season in ordered:
        if season.season_type == SeasonType.EXTRA.value:
            continue
        number += 1
        if season.season_number != number:
            numbers[season.id] = number
            season.season_number = number
    s.flush()
    if numbers and collection.episode_identifier == EpisodeIdentifier.SEASONAL.value:
        _renumber_episodes(s, collection, numbers)


def _renumber_episodes(s: Session, collection: Collection, numbers: dict[int, int]) -> None:
    with_files = _with_files(s, collection)
    episodes = [
        episode for episode in s.scalars(
            select(Episode).where(Episode.collection_id == collection.id, Episode.season_id.in_(numbers)).order_by(Episode.index)
        )
        if episode.id not in with_files
    ]
    _rewrite(s, collection, episodes, numbers)


def match_seasons_of_downloaded(s: Session, collection: Collection, episode_ids: set[int] | None = None) -> int:
    """Give the collection's episodes with files, or only these of them, the number of the season they are in now, as
    the ones without files have, before their files move into their season folders: S2024E03 in the third season
    becomes S03E03. Returns how many changed.

    ``s`` is a write transaction's session."""
    if collection.episode_identifier != EpisodeIdentifier.SEASONAL.value:
        return 0
    numbers = {season.id: season.season_number for season in collection.seasons}
    with_files = _with_files(s, collection)
    episodes = [
        episode for episode in s.scalars(
            select(Episode).where(
                Episode.collection_id == collection.id,
                Episode.id.in_(with_files if episode_ids is None else with_files & episode_ids),
            ).order_by(Episode.index)
        )
        if (match := _SEASONAL.match(episode.episode_identifier or "")) and episode.season_id in numbers
        and int(match.group(1)) != numbers[episode.season_id]
    ]
    _rewrite(s, collection, episodes, numbers)
    return len(episodes)


def _with_files(s: Session, collection: Collection) -> set[int]:
    return set(s.scalars(
        select(MediaDownloadBase.media_item_id).join(Episode, Episode.id == MediaDownloadBase.media_item_id)
        .where(Episode.collection_id == collection.id)
    ))


def _rewrite(s: Session, collection: Collection, episodes: list[Episode], numbers: dict[int, int]) -> None:
    """Give each seasonal episode its season's number, keeping its own episode number where it is free."""
    episodes = [episode for episode in episodes if _SEASONAL.match(episode.episode_identifier or "")]
    if not episodes:
        return
    moving = {episode.id for episode in episodes}
    taken = set(s.scalars(
        select(Episode.episode_identifier).where(Episode.collection_id == collection.id, Episode.id.not_in(moving))
    ))
    wanted: dict[int, str] = {}
    for episode in episodes:
        season_number = numbers[episode.season_id]
        episode_number = int(_SEASONAL.match(episode.episode_identifier).group(2))
        identifier = f"ep.S{season_number:02d}E{episode_number:02d}"
        while identifier in taken:
            # An episode with files still has this one from before.
            episode_number += 1
            identifier = f"ep.S{season_number:02d}E{episode_number:02d}"
        taken.add(identifier)
        wanted[episode.id] = identifier
    _assign(s, episodes, wanted)


def _assign(s: Session, episodes: list[Episode], wanted: dict[int, str]) -> None:
    if not episodes:
        return
    # Two passes, because identifiers are unique in a collection.
    for episode in episodes:
        episode.episode_identifier = f"renumbering.{episode.id}"
    s.flush()
    for episode in episodes:
        episode.episode_identifier = wanted[episode.id]
    s.flush()
