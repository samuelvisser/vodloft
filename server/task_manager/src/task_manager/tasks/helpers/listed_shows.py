"""Index the episodes of a show whose Source lists them (``Feature.EPISODE_LISTS``).

VODLoft keeps the seasons of a Source that has them, and makes one season per
upload year for a Source that does not. The show's episode identification says
how its episodes are identified:

- Seasonal: the Source's episode number in its season, S02E05, or for a season
  per year the upload order within the year, S2024E01.
- Date-based: the upload date and time.
- Numbered: the upload order across the show, 1, 2, 3.

Only episodes with the Source's main tag follow that scheme. Every other tag,
such as a YouTube Short, counts on its own across the show: short.1, short.2.

A new episode is numbered after the episodes VODLoft already has, so existing
file names never change. Numbering follows upload order, so the episodes are
saved together once the Source has listed them all.

A Source with ``Feature.CATALOGUE_REFRESH`` also keeps the episodes VODLoft
has up to date: their titles, descriptions and pictures, and whether the
Source still has them. An episode the Source no longer has keeps its
downloaded files and is not downloaded again until it is back.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Episode, Season, Show
from backend.services.seasons import create_season_record
from backend.types.episode_types import EpisodePublishStatus
from backend.types.media_types import MediaType
from backend.types.show_types import EpisodeIdentifier
from backend.utils.helpers import generate_uuid
from sources import MAIN_TAG, ItemRef, Source, VideoDetails
from .episodes.events import queue_episode_status_events
from .general import datetime_to_string
from .progress import update_progress

logger = logging.getLogger(__name__)

_LISTING_PROGRESS = 10
_SAVING_PROGRESS = 90

def _season_number(details: VideoDetails, fallback: datetime) -> int:
    if details.season is not None:
        return details.season.number
    return (details.published_at or fallback).year


def _order_key(details: VideoDetails, fallback: datetime):
    number = details.episode_number if details.episode_number is not None else 10**9
    return _season_number(details, fallback), number, details.published_at or fallback, details.slug


class _SeasonNumbers:
    """The episode numbers each season of the show already uses."""

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


def _next(identifiers: set[str], prefix: str) -> str:
    """The next free ``<prefix>.<number>`` after the highest one the show has."""
    numbers = [
        int(identifier.removeprefix(f"{prefix}."))
        for identifier in identifiers
        if identifier.startswith(f"{prefix}.") and identifier.removeprefix(f"{prefix}.").isdigit()
    ]
    return f"{prefix}.{max(numbers, default=0) + 1}"


def _identifier(
    show: Show, season: Season, details: VideoDetails, identifiers: set[str], numbers: _SeasonNumbers,
    fallback: datetime,
) -> str:
    if details.tag != MAIN_TAG:
        return _next(identifiers, details.tag)
    match EpisodeIdentifier(show.episode_identifier):
        case EpisodeIdentifier.DATE_BASED:
            identifier = f"ep.{datetime_to_string(details.published_at or fallback)}"
            # Two videos uploaded at the same moment: the second one is auxiliary.
            return _next(identifiers, "aux") if identifier in identifiers else identifier
        case EpisodeIdentifier.NUMBERED:
            return _next(identifiers, "ep")
        case EpisodeIdentifier.SEASONAL:
            number = numbers.take(season, details.episode_number if details.season else None)
            return f"ep.S{season.season_number:02d}E{number:02d}"


def _order_seasons(s: Session, show: Show) -> None:
    """Keep season indices in season order when an earlier season turns up later."""
    seasons = sorted(show.seasons, key=lambda season: season.season_number)
    if [season.index for season in seasons] == list(range(1, len(seasons) + 1)):
        return
    # Two passes, because (show_id, index) is unique.
    for offset, season in enumerate(seasons, start=1):
        season.index = -offset
    s.flush()
    for offset, season in enumerate(seasons, start=1):
        season.index = offset
    s.flush()


def _episode_slug(s: Session, show: Show, source_slug: str) -> str:
    """The Source's own slug, unless an episode of another show already has it."""
    taken = s.scalar(select(func.count()).select_from(Episode).where(Episode.slug == source_slug))
    return f"{show.slug}-{source_slug}" if taken else source_slug


def known_episode_slugs(s: Session, show: Show) -> frozenset[str]:
    return frozenset(s.scalars(select(Episode.source_slug).where(Episode.show_id == show.id)))


def _list_new_episodes(s: Session, show: Show, source: Source, progress) -> list[VideoDetails]:
    url, title, known = show.sharing_url, show.title, known_episode_slugs(s, show)
    # No transaction stays open while the Source looks videos up.
    s.rollback()
    update_progress(progress, _LISTING_PROGRESS, f"Listing the episodes of '{title}' at {source.name}")
    found: list[VideoDetails] = []
    for details in source.list_episodes(url, known=known):
        found.append(details)
        update_progress(
            progress, _LISTING_PROGRESS,
            f"Found {len(found)} new {'episode' if len(found) == 1 else 'episodes'} of '{title}' at {source.name}",
        )
    return found


def index_listed_show(s: Session, *, show_id: int, source: Source, progress=None, dry_run: bool = False) -> int:
    """Add the show's new episodes. Returns how many were added, or would be added in a dry run."""
    show = s.get(Show, show_id)
    if show is None:
        return 0
    found = _list_new_episodes(s, show, source, progress)
    if dry_run:
        for details in found:
            logger.info("Dry run: would add %s (%s)", details.slug, details.title)
        return len(found)
    return add_listed_episodes(s, show_id=show_id, found=found, progress=progress)


def add_listed_episodes(s: Session, *, show_id: int, found: list[VideoDetails], progress=None) -> int:
    """Save episodes a Source found, numbered after the ones the show has. Returns how many were added."""
    if not found:
        return 0
    show = s.get(Show, show_id)
    if show is None:
        return 0
    known = known_episode_slugs(s, show)
    now = datetime.now(timezone.utc)
    new: dict[str, VideoDetails] = {}
    for details in found:
        if details.slug not in known:
            new.setdefault(details.slug, details)
    ordered = sorted(new.values(), key=lambda details: _order_key(details, now))
    update_progress(progress, _SAVING_PROGRESS, f"Saving {len(ordered)} new episodes of '{show.title}'")

    # A Source's own season is found by its slug, a season per year by its year.
    by_slug = {season.slug: season for season in show.seasons}
    by_year = {season.season_number: season for season in show.seasons}
    identifiers = set(s.scalars(select(Episode.episode_identifier).where(Episode.show_id == show.id)))
    numbers = _SeasonNumbers(s)
    next_index = (s.scalar(select(func.max(Episode.index)).where(Episode.show_id == show.id)) or 0) + 1
    created: list[Episode] = []
    for details in ordered:
        number = _season_number(details, now)
        ref = details.season
        season = by_slug.get(ref.slug) if ref is not None else by_year.get(number)
        if season is not None and season.season_number != number:
            # A season picked when the show was added, before VODLoft knew its number.
            season.season_number = number
        if season is None:
            season = create_season_record(
                s, show_id=show.id, index=max((x.index for x in show.seasons), default=0) + 1,
                slug=ref.slug if ref else str(number),
                name=ref.name if ref else str(number),
                season_number=number, update_show_profiles=True,
            )
            by_slug[season.slug] = by_year[number] = season
            s.refresh(show)
        identifier = _identifier(show, season, details, identifiers, numbers, now)
        identifiers.add(identifier)
        episode = Episode(
            uuid=generate_uuid(),
            type=MediaType.EPISODE.value,
            source_key=show.source_key,
            show_id=show.id,
            season_id=season.id,
            index=next_index,
            episode_identifier=identifier,
            slug=_episode_slug(s, show, details.slug),
            source_slug=details.slug,
            publish_status=EpisodePublishStatus.PUBLISHED_FINAL.value,
            metadata_is_final=True,
            sharing_url=details.url,
            published_date=details.published_at,
            title=details.title,
            description=details.description,
            duration=details.duration or 0.0,
            thumbnail_landscape_path=details.image_url,
            background_image_path=details.image_url,
            drm_protected=details.drm_protected,
            needs_subscription=details.needs_subscription,
        )
        s.add(episode)
        s.flush()
        created.append(episode)
        next_index += 1

    _order_seasons(s, show)
    for episode in created:
        queue_episode_status_events(
            s, episode=episode, show=show, old_status=None,
            new_status=EpisodePublishStatus.PUBLISHED_FINAL, was_created=True,
        )
    return len(created)


@dataclass(frozen=True)
class RefreshCounts:
    updated: int = 0
    removed: int = 0
    returned: int = 0


def refresh_listed_show(s: Session, *, show_id: int, source: Source) -> RefreshCounts:
    """Bring the show's episodes up to date with what the Source says about them now.

    File names never change, so a new title only shows in VODLoft and in files
    downloaded from now on.
    """
    show = s.get(Show, show_id)
    if show is None:
        return RefreshCounts()
    url = show.sharing_url
    items = [
        ItemRef(slug, item_url or "")
        for slug, item_url in s.execute(
            select(Episode.source_slug, Episode.sharing_url).where(Episode.show_id == show_id, Episode.source_slug.is_not(None))
        )
    ]
    if not items:
        return RefreshCounts()
    # No transaction stays open while the Source looks videos up.
    s.rollback()
    refresh = source.refresh_items(url, items)
    updated = removed = returned = 0
    for episode in s.scalars(select(Episode).where(Episode.show_id == show_id)):
        if episode.source_slug in refresh.removed:
            if not episode.removed_from_source:
                episode.removed_from_source = True
                removed += 1
            continue
        details = refresh.details.get(episode.source_slug)
        if details is None:
            continue
        if episode.removed_from_source:
            episode.removed_from_source = False
            returned += 1
        changes = {"title": details.title, "description": details.description}
        if details.image_url:
            changes |= {"thumbnail_landscape_path": details.image_url, "background_image_path": details.image_url}
        changed = False
        for name, value in changes.items():
            if value is not None and getattr(episode, name) != value:
                setattr(episode, name, value)
                changed = True
        updated += changed
    s.commit()
    if removed or returned:
        logger.info("'%s': %d episodes no longer at the Source, %d back", show.title, removed, returned)
    return RefreshCounts(updated=updated, removed=removed, returned=returned)
