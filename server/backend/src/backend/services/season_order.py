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

from backend.db.models import Collection, CollectionList, CollectionListItem, Episode
from backend.services.season_state import EpisodeDraft, ListDraft, SeasonDraft, SeasonsState, apply_state, load_state
from backend.types.collection_contracts import collection_contract
from backend.types.collection_types import EpisodeIdentifier
from backend.types.season_types import SeasonType

_SEASONAL = re.compile(r"^ep\.S(\d+)E(\d+)$")
_LAST = datetime.max.replace(tzinfo=timezone.utc)


def season_year(season) -> int | None:
    """The upload year of a season per year. Found by its slug, which stays when the user renames the season."""
    return int(season.slug) if len(season.slug) == 4 and season.slug.isdigit() else None


def link_first_videos(state: SeasonsState) -> dict[int, datetime]:
    """When the first video of the collection that each playlist has came out, by playlist id. YouTube does not say
    when a playlist was made, so this stands in for it."""
    published: dict[str, datetime] = {}
    for episode in state.episodes.values():
        if episode.published_date is not None:
            moment = _aware(episode.published_date)
            published[episode.source_slug] = min(moment, published.get(episode.source_slug, moment))
    firsts: dict[int, datetime] = {}
    for playlist in state.lists:
        dates = [published[slug] for slug in playlist.items if slug in published]
        if dates:
            firsts[playlist.id] = min(dates)
    return firsts


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _dated_order(state: SeasonsState) -> list[SeasonDraft]:
    """Seasons per year by their year, every other season right after the year it started in. In a Music collection
    the albums come after those, in the artist's order."""
    collection = state.collection
    by_playlist = link_first_videos(state)
    # A season of several lists starts with the first of them.
    playlist_starts: dict[int, datetime] = {}
    for playlist in collection.lists:
        if playlist.season_id is not None and playlist.id in by_playlist:
            start = by_playlist[playlist.id]
            playlist_starts[playlist.season_id] = min(start, playlist_starts.get(playlist.season_id, start))
    firsts: dict[int, datetime] = {}
    for episode in state.episodes.values():
        if episode.published_date is not None:
            moment = _aware(episode.published_date)
            firsts[episode.season_id] = min(moment, firsts.get(episode.season_id, moment))

    # An artist's albums follow the order the artist gives them at the Site, after the singles.
    site_order = collection_contract(collection.type).site_order
    album_places: dict[int, int] = {}
    for link in collection.lists if site_order else ():
        if link.season_id is not None:
            album_places[link.season_id] = min(link.site_position, album_places.get(link.season_id, link.site_position))

    # A feed's own season, such as Shorts, comes first with the channel's other videos.
    feeds = {season_id for season_id in (collection.feed_seasons or {}).values() if season_id is not None}

    def key(season: SeasonDraft):
        if season.season_type == SeasonType.EXTRA.value:
            return (2, 0, 0, _LAST, season.index)
        if season.loose:
            # The videos in no playlist come first, as a channel's Videos do.
            return (-1, 0, 0, _LAST, season.index)
        if season.id in feeds and season.id not in playlist_starts:
            return (-1, 1, 0, _LAST, season.index)
        if season.id in album_places:
            return (1, album_places[season.id], 0, _LAST, season.index)
        year = season_year(season)
        if year is not None:
            return (0, year, 0, _LAST, season.index)
        start = playlist_starts.get(season.id) or firsts.get(season.id)
        start = start or _aware(season.created_at or state.now)
        if site_order:
            # Another album, such as one split from a video by its chapters, after the artist's own, by date.
            return (1, len(album_places), 1, start, season.index)
        return (0, start.year, 1, start, season.index)

    return sorted(collection.seasons, key=key)


def _slot_in(ordered: list[SeasonDraft], made: set[int], dated: list[SeasonDraft]) -> list[SeasonDraft]:
    """The seasons in this order, each made one right after the season that comes before it in ``dated``."""
    result = [season for season in ordered if season.id not in made]
    before = None
    for season in dated:
        if season.id in made:
            result.insert(result.index(before) + 1 if before is not None else 0, season)
        before = season
    return result


def arrange(state: SeasonsState) -> None:
    """Put the collection's seasons in order after seasons were added or videos moved."""
    collection = state.collection
    seasons = state.ordered_seasons()
    if collection.custom_season_order:
        # The user's order stays, and a new season goes last, except a season per year made just now: that goes where
        # its year puts it, so the years stay in order. The numbers close up around seasons that went.
        made = state.made & {season.id for season in seasons if season_year(season) is not None}
        state.made.clear()
        _close_up(state, _slot_in(seasons, made, _dated_order(state)) if made else seasons)
    elif (any(playlist.season_id is not None for playlist in collection.lists) or any(season.loose for season in seasons)
          or any(season_id is not None for season_id in (collection.feed_seasons or {}).values())
          # Numbered in their order once already, such as before a list's season went: they stay so.
          or any(season_year(season) not in (None, season.season_number) for season in seasons)):
        renumber_seasons(state, _dated_order(state))
    else:
        _set_indices(sorted(seasons, key=lambda season: season.season_number))
    number_lists(state)


def arrange_seasons(s: Session, collection: Collection) -> None:
    """Put the collection's seasons in order after seasons were added or videos moved.

    ``s`` is a write transaction's session."""
    state = load_state(s, collection)
    arrange(state)
    apply_state(s, state)


def _in_list_order(links: list, firsts: dict[int, datetime]) -> list:
    """A season's lists in the order its videos go: the list whose first video came out first comes first, so a
    "Part 1" playlist comes before "Part 2"."""
    return sorted(links, key=lambda link: (firsts.get(link.id, _LAST), link.site_position, link.id))


def lists_by_season(state: SeasonsState) -> dict[int, list[ListDraft]]:
    """The lists of each season that has some, in the order its videos go (``_in_list_order``)."""
    firsts = link_first_videos(state)
    by_season: dict[int, list[ListDraft]] = {}
    for link in state.lists:
        if link.season_id is not None:
            by_season.setdefault(link.season_id, []).append(link)
    return {season_id: _in_list_order(links, firsts) for season_id, links in by_season.items()}


def season_lists(s: Session, collection: Collection, season_id: int) -> list[CollectionList]:
    """The lists of one season of the collection as it is saved, in the order its videos go (``_in_list_order``),
    without reading the whole collection."""
    links = [link for link in collection.lists if link.season_id == season_id]
    if not links:
        return []
    firsts = {
        list_id: _aware(first) for list_id, first in s.execute(
            select(CollectionListItem.list_id, func.min(Episode.published_date))
            .join(Episode, (Episode.collection_id == collection.id) & (Episode.source_slug == CollectionListItem.source_slug))
            .where(CollectionListItem.list_id.in_([link.id for link in links])).group_by(CollectionListItem.list_id)
        ) if first is not None
    }
    return _in_list_order(links, firsts)


def number_lists(state: SeasonsState) -> None:
    """Number the episodes of each season of lists in the order its Site lists them, as a playlist or an album's
    tracks are, so S03E01 is the playlist's first video. A season of several lists has the videos of its first list
    first, then those of the next. An episode with files keeps its number, and the others go around it."""
    if state.collection.episode_identifier != EpisodeIdentifier.SEASONAL.value:
        return
    link_season_ids = {link.season_id for link in state.lists if link.season_id is not None}
    # The identifiers that stay: of episodes with files, and of episodes in no link season.
    taken = {
        episode.episode_identifier for episode in state.episodes.values()
        if episode.has_files or episode.season_id not in link_season_ids or episode.part_of is not None
    }
    for season_id, links in lists_by_season(state).items():
        season = state.seasons.get(season_id)
        if season is None:
            continue
        places: dict[str, tuple[int, int]] = {}
        for order, link in enumerate(links):
            for position, slug in enumerate(link.items):
                places.setdefault(slug, (order, position))
        unplaced = (len(links), 0)
        rows = sorted(
            (episode for episode in state.episodes.values() if episode.season_id == season.id and episode.part_of is None),
            key=lambda episode: (places.get(episode.source_slug, unplaced), episode.index),
        )
        number = 0
        for episode in rows:
            if episode.has_files or not _SEASONAL.match(episode.episode_identifier or ""):
                continue
            number += 1
            while (identifier := f"ep.S{season.season_number:02d}E{number:02d}") in taken:
                number += 1
            taken.add(identifier)
            episode.episode_identifier = identifier


def number_in_link_order(s: Session, collection: Collection) -> None:
    """``number_lists`` for the collection as it is.

    ``s`` is a write transaction's session."""
    state = load_state(s, collection)
    number_lists(state)
    apply_state(s, state)


def _set_indices(ordered: list[SeasonDraft]) -> None:
    for offset, season in enumerate(ordered, start=1):
        season.index = offset


def renumber_seasons(state: SeasonsState, ordered: list[SeasonDraft]) -> None:
    """Show the seasons in this order and number them 1, 2, 3 in it. Extras stay season 0."""
    _set_indices(ordered)
    numbers: dict[int, int] = {}
    number = 0
    for season in ordered:
        if season.season_type == SeasonType.EXTRA.value:
            continue
        number += 1
        if season.season_number != number:
            numbers[season.id] = number
            season.season_number = number
    if numbers and state.collection.episode_identifier == EpisodeIdentifier.SEASONAL.value:
        _renumber_episodes(state, numbers)


def _close_up(state: SeasonsState, ordered: list[SeasonDraft]) -> None:
    """Keep the seasons in this order and number the numbered ones 1, 2, 3 in it, so no number is left out. A season
    numbered 0, such as Specials, stays 0."""
    _set_indices(ordered)
    numbers: dict[int, int] = {}
    numbered = [season for season in ordered if season.season_type != SeasonType.EXTRA.value and season.season_number != 0]
    for number, season in enumerate(numbered, start=1):
        if season.season_number != number:
            numbers[season.id] = number
            season.season_number = number
    if numbers and state.collection.episode_identifier == EpisodeIdentifier.SEASONAL.value:
        _renumber_episodes(state, numbers)


def _renumber_episodes(state: SeasonsState, numbers: dict[int, int]) -> None:
    _rewrite(state, [
        episode for episode in state.in_index_order() if episode.season_id in numbers and not episode.has_files
    ])


def match_downloaded(state: SeasonsState, episode_ids: set[int] | None = None) -> int:
    """Give the collection's episodes with files, or only these of them, the number of the season they are in now, as
    the ones without files have, before their files move into their season folders: S2024E03 in the third season
    becomes S03E03. Returns how many changed."""
    if state.collection.episode_identifier != EpisodeIdentifier.SEASONAL.value:
        return 0
    episodes = [
        episode for episode in state.in_index_order()
        if episode.has_files and (episode_ids is None or episode.id in episode_ids)
        and (match := _SEASONAL.match(episode.episode_identifier or "")) and episode.season_id in state.seasons
        and int(match.group(1)) != state.seasons[episode.season_id].season_number
    ]
    _rewrite(state, episodes)
    return len(episodes)


def match_seasons_of_downloaded(s: Session, collection: Collection, episode_ids: set[int] | None = None) -> int:
    """``match_downloaded`` for the collection as it is.

    ``s`` is a write transaction's session."""
    state = load_state(s, collection)
    changed = match_downloaded(state, episode_ids)
    apply_state(s, state)
    return changed


def _rewrite(state: SeasonsState, episodes: list[EpisodeDraft]) -> None:
    """Give each seasonal episode its season's number, keeping its own episode number where it is free."""
    episodes = [episode for episode in episodes if _SEASONAL.match(episode.episode_identifier or "")]
    if not episodes:
        return
    moving = {episode.id for episode in episodes}
    taken = {episode.episode_identifier for episode in state.episodes.values() if episode.id not in moving}
    for episode in episodes:
        season_number = state.seasons[episode.season_id].season_number
        episode_number = int(_SEASONAL.match(episode.episode_identifier).group(2))
        identifier = f"ep.S{season_number:02d}E{episode_number:02d}"
        while identifier in taken:
            # An episode with files still has this one from before.
            episode_number += 1
            identifier = f"ep.S{season_number:02d}E{episode_number:02d}"
        taken.add(identifier)
        episode.episode_identifier = identifier
