"""Index the episodes of a collection whose Source lists them (``Feature.EPISODE_LISTS``).

VODLoft keeps the seasons of a Source that has them, and makes one season per
upload year for a Source that does not. The collection's episode identification says
how its episodes are identified:

- Seasonal: the Source's episode number in its season, S02E05, or for a season
  per year the upload order within the year, S2024E01.
- Date-based: the upload date and time.
- Numbered: the upload order across the collection, 1, 2, 3.

Only episodes with the Source's main tag follow that scheme. Every other tag,
such as a YouTube Short, counts on its own across the collection: short.1, short.2.

A collection is indexed from each of its links in turn. A link's placement says
where its videos go: the Source's seasons or a season per year, one season named
after the link, or Specials. A video several links list is kept once, by the
link highest in the collection's order, and moves there while it has no files.

A new episode is numbered after the episodes VODLoft already has, so existing
file names never change. Numbering follows upload order, so the episodes are
saved together once the Source has listed them all.

A Source with ``Feature.PENDING_CHECKS`` also lists upcoming and live videos.
VODLoft adds them with their status, unless their Site has that turned off, and
follows them until they are published. They are not downloaded before then.

A Source with ``Feature.CATALOGUE_REFRESH`` also keeps the episodes VODLoft
has up to date: their titles, descriptions and pictures, and whether the
Source still has them. An episode the Source no longer has keeps its
downloaded files and is not downloaded again until it is back.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.db.models import CollectionLink, CollectionLinkItem, Episode, MediaDownloadBase, Season, Collection
from backend.db.core import run_write_transaction
from backend.services.media_access import lock_refused
from backend.services.seasons import create_season_record
from backend.services.metadata_refresh import new_item_metadata_is_final
from backend.services.pending_episodes import site_follows_pending
from backend.types.episode_types import PENDING_EPISODE_PUBLISH_STATUSES, EpisodePublishStatus
from backend.types.media_types import MediaType
from backend.types.collection_link_types import LinkPlacement
from backend.types.collection_types import EpisodeIdentifier
from backend.utils.helpers import slugify
from backend.utils.helpers import generate_uuid
from sources import MAIN_TAG, Feature, ItemRef, SeasonRef, Source, VideoDetails, get_source
from .episodes.events import queue_episode_status_events
from .general import datetime_to_string
from .progress import update_progress
from task_manager.tasks.media_download_operations import dispatch_queued_media_download_operations
from .locked_media import open_up
from .refreshed_metadata import apply_refreshed_details, check_upgrades_after_refresh

logger = logging.getLogger(__name__)

_LISTING_PROGRESS = 10
_SAVING_PROGRESS = 90
# Seasons per upload year are numbered by the year, so named seasons stay below it.
_FIRST_YEAR = 1900

def _season_number(details: VideoDetails, fallback: datetime) -> int:
    if details.season is not None:
        return details.season.number
    return (details.published_at or fallback).year


def _order_key(details: VideoDetails, fallback: datetime):
    number = details.episode_number if details.episode_number is not None else 10**9
    return _season_number(details, fallback), number, details.published_at or fallback, details.slug


class _SeasonNumbers:
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


def _next(identifiers: set[str], prefix: str) -> str:
    """The next free ``<prefix>.<number>`` after the highest one the collection has."""
    numbers = [
        int(identifier.removeprefix(f"{prefix}."))
        for identifier in identifiers
        if identifier.startswith(f"{prefix}.") and identifier.removeprefix(f"{prefix}.").isdigit()
    ]
    return f"{prefix}.{max(numbers, default=0) + 1}"


def _identifier(
    collection: Collection, season: Season, details: VideoDetails, identifiers: set[str], numbers: _SeasonNumbers,
    fallback: datetime,
) -> str:
    if details.tag != MAIN_TAG:
        return _next(identifiers, details.tag)
    match EpisodeIdentifier(collection.episode_identifier):
        case EpisodeIdentifier.DATE_BASED:
            identifier = f"ep.{datetime_to_string(details.published_at or fallback)}"
            # Two videos uploaded at the same moment: the second one is auxiliary.
            return _next(identifiers, "aux") if identifier in identifiers else identifier
        case EpisodeIdentifier.NUMBERED:
            return _next(identifiers, "ep")
        case EpisodeIdentifier.SEASONAL:
            number = numbers.take(season, details.episode_number if details.season else None)
            return f"ep.S{season.season_number:02d}E{number:02d}"


def _order_seasons(s: Session, collection: Collection) -> None:
    """Keep season indices in season order when an earlier season turns up later."""
    seasons = sorted(collection.seasons, key=lambda season: season.season_number)
    if [season.index for season in seasons] == list(range(1, len(seasons) + 1)):
        return
    # Two passes, because (collection_id, index) is unique.
    for offset, season in enumerate(seasons, start=1):
        season.index = -offset
    s.flush()
    for offset, season in enumerate(seasons, start=1):
        season.index = offset
    s.flush()


def _episode_slug(s: Session, collection: Collection, source_slug: str) -> str:
    """The Source's own slug, unless an episode of another collection already has it."""
    taken = s.scalar(select(func.count()).select_from(Episode).where(Episode.slug == source_slug))
    return f"{collection.slug}-{source_slug}" if taken else source_slug


def adds_pending(collection: Collection) -> bool:
    """Whether upcoming and live videos of the collection are added before they are published."""
    return get_source(collection.source_key).has(Feature.PENDING_CHECKS) and site_follows_pending(collection.site_key)


def date_based_identifier(s: Session, episode: Episode, published_at: datetime) -> str | None:
    """The identifier a main episode of a date-based collection gets for a new publication date,
    or None when it keeps its own: an upcoming video that started later than planned moves."""
    collection = episode.collection
    if collection.episode_identifier != EpisodeIdentifier.DATE_BASED.value:
        return None
    identifier = f"ep.{datetime_to_string(published_at)}"
    if not episode.episode_identifier.startswith("ep.") or episode.episode_identifier == identifier:
        return None
    identifiers = set(s.scalars(select(Episode.episode_identifier).where(
        Episode.collection_id == collection.id, Episode.id != episode.id,
    )))
    return _next(identifiers, "aux") if identifier in identifiers else identifier


def known_episode_slugs(s: Session, collection: Collection) -> frozenset[str]:
    return frozenset(s.scalars(select(Episode.source_slug).where(Episode.collection_id == collection.id)))


def link_item_slugs(s: Session, link_id: int) -> frozenset[str]:
    """The videos a link already listed, which it does not look up again."""
    return frozenset(s.scalars(select(CollectionLinkItem.source_slug).where(CollectionLinkItem.link_id == link_id)))


def collection_links(s: Session, collection_id: int) -> list[tuple[int, str]]:
    """The collection's links as (id, url), in the order that decides which link keeps a shared video."""
    return [(link_id, url) for link_id, url in s.execute(
        select(CollectionLink.id, CollectionLink.url)
        .where(CollectionLink.collection_id == collection_id)
        .order_by(CollectionLink.position, CollectionLink.id)
    )]


def _list_new_episodes(s: Session, collection: Collection, source: Source, progress) -> list[tuple[int, list[VideoDetails]]]:
    title = collection.title
    links = [(link_id, url, link_item_slugs(s, link_id)) for link_id, url in collection_links(s, collection.id)]
    # No transaction stays open while the Source looks videos up.
    s.rollback()
    update_progress(progress, _LISTING_PROGRESS, f"Listing the episodes of '{title}' at {source.name}")
    found: list[tuple[int, list[VideoDetails]]] = []
    count = 0
    for link_id, url, known in links:
        listed: list[VideoDetails] = []
        for details in source.list_episodes(url, known=known):
            listed.append(details)
            count += 1
            message = f"Found {count} new {'episode' if count == 1 else 'episodes'} of '{title}' at {source.name}"
            if progress:
                # A Source can't say how many episodes there are, so the count is shown instead of a percentage.
                progress.set(_LISTING_PROGRESS, message, meta={"found": count})
            else:
                update_progress(progress, _LISTING_PROGRESS, message)
        found.append((link_id, listed))
    return found


def index_listed_collection(s: Session, *, collection_id: int, source: Source, progress=None, dry_run: bool = False) -> int:
    """Add the new episodes of each of the collection's links. Returns how many were added, or would be added in a dry run."""
    collection = s.get(Collection, collection_id)
    if collection is None:
        return 0
    title = collection.title
    found = _list_new_episodes(s, collection, source, progress)
    s.rollback()
    total = sum(len(listed) for _link_id, listed in found)
    if dry_run:
        for _link_id, listed in found:
            for details in listed:
                logger.info("Dry run: would add %s (%s)", details.slug, details.title)
        return total
    if total:
        update_progress(progress, _SAVING_PROGRESS, f"Saving {total} new episodes of '{title}'")

    def save(w: Session) -> int:
        return sum(
            add_listed_episodes(w, collection_id=collection_id, link_id=link_id, found=listed)
            for link_id, listed in found if listed
        )

    return run_write_transaction(save)


def _has_files(s: Session, episode: Episode) -> bool:
    return s.scalar(select(func.count()).select_from(MediaDownloadBase).where(MediaDownloadBase.media_item_id == episode.id)) > 0


class _Placer:
    """Finds the season each link's videos go to, and makes it when the collection has none yet."""

    def __init__(self, s: Session, collection: Collection, now: datetime):
        self._s, self._collection, self._now = s, collection, now
        # A Source's own season is found by its slug, a season per year by its year.
        self._by_slug = {season.slug: season for season in collection.seasons}
        self._by_year = {season.season_number: season for season in collection.seasons}
        self.identifiers = set(s.scalars(select(Episode.episode_identifier).where(Episode.collection_id == collection.id)))
        self.numbers = _SeasonNumbers(s)

    def _create(self, *, slug: str, name: str, number: int) -> Season:
        collection = self._collection
        taken = {season.slug for season in collection.seasons}
        unique, suffix = slug, 2
        while unique in taken:
            unique, suffix = f"{slug}-{suffix}", suffix + 1
        season = create_season_record(
            self._s, collection_id=collection.id, index=max((x.index for x in collection.seasons), default=0) + 1,
            slug=unique, name=name, season_number=number, update_collection_profiles=True,
        )
        self._s.refresh(collection)
        return season

    def season(self, link: CollectionLink, ref: SeasonRef | None, published_at: datetime | None) -> Season:
        match LinkPlacement(link.placement):
            case LinkPlacement.ONE_SEASON:
                if link.season is None:
                    # A named season is numbered after the other named ones, below the seasons per year.
                    number = max(
                        (season.season_number for season in self._collection.seasons if 0 < season.season_number < _FIRST_YEAR),
                        default=0,
                    ) + 1
                    name = link.title or f"Season {number}"
                    link.season = self._create(slug=slugify(name) or str(number), name=name, number=number)
                    self._s.flush()
                return link.season
            case LinkPlacement.SPECIALS:
                specials = self._by_year.get(0)
                if specials is None:
                    specials = self._by_year[0] = self._create(slug="specials", name="Specials", number=0)
                return specials
        number = ref.number if ref is not None else (published_at or self._now).year
        season = self._by_slug.get(ref.slug) if ref is not None else self._by_year.get(number)
        if season is not None and season.season_number != number:
            # A season picked when the collection was added, before VODLoft knew its number.
            season.season_number = number
        if season is None:
            season = self._create(slug=ref.slug if ref else str(number), name=ref.name if ref else str(number), number=number)
            self._by_slug[season.slug] = self._by_year[number] = season
        return season

    def identifier(self, link: CollectionLink, season: Season, details: VideoDetails) -> str:
        own_numbers = LinkPlacement(link.placement) is LinkPlacement.SITE_SEASONS
        identifier = _identifier(
            self._collection, season, details if own_numbers else replace(details, season=None),
            self.identifiers, self.numbers, self._now,
        )
        self.identifiers.add(identifier)
        return identifier

    def move(self, episode: Episode, link: CollectionLink, season: Season) -> None:
        """Give an episode without files to the link that keeps it now. A seasonal number follows its new season."""
        episode.collection_link_id = link.id
        if episode.season_id == season.id:
            return
        episode.season_id = season.id
        if (
            self._collection.episode_identifier == EpisodeIdentifier.SEASONAL.value
            and episode.episode_identifier.startswith("ep.S")
        ):
            self.identifiers.discard(episode.episode_identifier)
            episode.episode_identifier = f"ep.S{season.season_number:02d}E{self.numbers.take(season, None):02d}"
            self.identifiers.add(episode.episode_identifier)


def _claim(s: Session, placer: _Placer, link: CollectionLink, episodes: list[Episode]) -> None:
    """A link lists episodes the collection already has: the one highest in the order keeps each of them."""
    positions = {other.id: other.position for other in link.collection.links}
    for episode in episodes:
        owner = positions.get(episode.collection_link_id)
        if owner is not None and owner <= link.position:
            continue
        if _has_files(s, episode):
            # Once an episode has a file it stays where it is.
            continue
        placer.move(episode, link, placer.season(link, None, episode.published_date))


def add_listed_episodes(s: Session, *, collection_id: int, found: list[VideoDetails], link_id: int | None = None) -> int:
    """Save episodes one of the collection's links listed, numbered after the ones the collection has. Returns how many
    were added. Without ``link_id`` they come from the collection's first link.

    ``s`` is a write transaction's session."""
    if not found:
        return 0
    collection = s.get(Collection, collection_id)
    if collection is None or not collection.links:
        return 0
    link = s.get(CollectionLink, link_id) if link_id is not None else collection.links[0]
    if link is None or link.collection_id != collection_id:
        return 0
    now = datetime.now(timezone.utc)
    pending_too = any(details.publish_status in PENDING_EPISODE_PUBLISH_STATUSES for details in found) and adds_pending(collection)
    listed: dict[str, VideoDetails] = {}
    for details in found:
        if details.publish_status in PENDING_EPISODE_PUBLISH_STATUSES and not pending_too:
            # A later scan adds it once it is published.
            continue
        listed.setdefault(details.slug, details)
    if not listed:
        return 0

    placer = _Placer(s, collection, now)
    known_items = link_item_slugs(s, link.id)
    s.add_all(CollectionLinkItem(link_id=link.id, source_slug=slug) for slug in listed if slug not in known_items)
    existing = list(s.scalars(select(Episode).where(Episode.collection_id == collection.id, Episode.source_slug.in_(listed))))
    _claim(s, placer, link, existing)
    known = {episode.source_slug for episode in existing}
    ordered = sorted((details for slug, details in listed.items() if slug not in known), key=lambda details: _order_key(details, now))

    next_index = (s.scalar(select(func.max(Episode.index)).where(Episode.collection_id == collection.id)) or 0) + 1
    created: list[tuple[Episode, EpisodePublishStatus]] = []
    for details in ordered:
        season = placer.season(link, details.season, details.published_at)
        identifier = placer.identifier(link, season, details)
        episode = Episode(
            uuid=generate_uuid(),
            type=MediaType.EPISODE.value,
            source_key=collection.source_key,
            collection_id=collection.id,
            season_id=season.id,
            collection_link_id=link.id,
            index=next_index,
            episode_identifier=identifier,
            slug=_episode_slug(s, collection, details.slug),
            source_slug=details.slug,
            publish_status=details.publish_status.value,
            # The metadata refresh sweep follows a new upload for a while, from when it is published; an older one is done.
            metadata_is_final=details.publish_status not in PENDING_EPISODE_PUBLISH_STATUSES and new_item_metadata_is_final(
                source_key=collection.source_key, site_key=collection.site_key, published_at=details.published_at,
            ),
            scheduled_date=details.scheduled_at,
            sharing_url=details.url,
            published_date=details.published_at,
            title=details.title,
            description=details.description,
            duration=details.duration or 0.0,
            author_name=details.author_name,
            thumbnail_landscape_path=details.image_url,
            background_image_path=details.image_url,
            drm_protected=details.drm_protected,
            access=details.access,
        )
        s.add(episode)
        s.flush()
        created.append((episode, details.publish_status))
        next_index += 1

    s.flush()
    _order_seasons(s, collection)
    for episode, status in created:
        queue_episode_status_events(
            s, episode=episode, collection=collection, old_status=None, new_status=status, was_created=True,
        )
    return len(created)


def claim_listed_items(s: Session, *, collection_id: int, link_id: int, slugs: set[str]) -> None:
    """Note that a link lists episodes the collection already has, which it keeps if it is higher in the order.

    ``s`` is a write transaction's session."""
    link = s.get(CollectionLink, link_id)
    if link is None or link.collection_id != collection_id or not slugs:
        return
    known_items = link_item_slugs(s, link.id)
    s.add_all(CollectionLinkItem(link_id=link.id, source_slug=slug) for slug in slugs if slug not in known_items)
    existing = list(s.scalars(select(Episode).where(Episode.collection_id == collection_id, Episode.source_slug.in_(slugs))))
    _claim(s, _Placer(s, link.collection, datetime.now(timezone.utc)), link, existing)
    s.flush()
    _order_seasons(s, link.collection)


@dataclass(frozen=True)
class RefreshCounts:
    updated: int = 0
    removed: int = 0
    returned: int = 0


def refresh_listed_collection(s: Session, *, collection_id: int, source: Source) -> RefreshCounts:
    """Bring the collection's episodes up to date with what the Source says about them now, link by link.

    File names never change, so a new title only shows in VODLoft and in files
    downloaded from now on. An episode that left its link but is still on
    another of the collection's links goes to that link, unless it has files.
    """
    collection = s.get(Collection, collection_id)
    if collection is None:
        return RefreshCounts()
    title = collection.title
    links = collection_links(s, collection_id)
    if not links:
        return RefreshCounts()
    first = links[0][0]
    work: list[tuple[int, str, list[ItemRef]]] = []
    for link_id, url in links:
        owned = Episode.collection_link_id == link_id
        if link_id == first:
            owned = owned | Episode.collection_link_id.is_(None)
        items = [
            ItemRef(slug, item_url or "")
            for slug, item_url in s.execute(
                select(Episode.source_slug, Episode.sharing_url)
                .where(Episode.collection_id == collection_id, Episode.source_slug.is_not(None), owned)
            )
        ]
        if items:
            work.append((link_id, url, items))
    # No transaction stays open while the Source looks videos up.
    s.rollback()
    counts = RefreshCounts()
    for link_id, url, items in work:
        refresh = source.refresh_items(url, items)
        slugs = frozenset(item.slug for item in items)
        found = run_write_transaction(lambda w: _apply_refresh(w, collection_id, refresh, slugs))
        if refresh.listed is not None and len(links) > 1:
            left = slugs - refresh.listed - refresh.removed
            if left:
                run_write_transaction(lambda w: _leave_link(w, collection_id, link_id, left))
        counts = RefreshCounts(
            updated=counts.updated + found.updated, removed=counts.removed + found.removed,
            returned=counts.returned + found.returned,
        )
    if counts.removed or counts.returned:
        logger.info("'%s': %d episodes no longer at the Source, %d back", title, counts.removed, counts.returned)
    return counts


def _leave_link(s: Session, collection_id: int, link_id: int, slugs: frozenset[str]) -> None:
    """Episodes a link no longer lists, such as a video taken out of a playlist, which the Site still has."""
    collection = s.get(Collection, collection_id)
    link = s.get(CollectionLink, link_id)
    if collection is None or link is None:
        return
    s.execute(delete(CollectionLinkItem).where(CollectionLinkItem.link_id == link_id, CollectionLinkItem.source_slug.in_(slugs)))
    holders: dict[str, CollectionLink] = {}
    links = {other.id: other for other in collection.links}
    for other_id, slug in s.execute(
        select(CollectionLinkItem.link_id, CollectionLinkItem.source_slug)
        .where(CollectionLinkItem.link_id.in_(links), CollectionLinkItem.source_slug.in_(slugs))
    ):
        other = links[other_id]
        if slug not in holders or (other.position, other.id) < (holders[slug].position, holders[slug].id):
            holders[slug] = other
    if not holders:
        # Only this link had them: they stay where they are.
        return
    placer = _Placer(s, collection, datetime.now(timezone.utc))
    for episode in s.scalars(select(Episode).where(Episode.collection_id == collection_id, Episode.source_slug.in_(holders))):
        if episode.collection_link_id not in (link_id, None) or _has_files(s, episode):
            continue
        holder = holders[episode.source_slug]
        placer.move(episode, holder, placer.season(holder, None, episode.published_date))
    s.flush()
    _order_seasons(s, collection)


def _apply_refresh(s: Session, collection_id: int, refresh, slugs: frozenset[str]) -> RefreshCounts:
    updated = removed = returned = opened = 0
    for episode in s.scalars(select(Episode).where(Episode.collection_id == collection_id, Episode.source_slug.in_(slugs))):
        if episode.source_slug in refresh.removed:
            if not episode.removed_from_source:
                episode.removed_from_source = True
                removed += 1
            continue
        details = refresh.details.get(episode.source_slug)
        access = refresh.refused.get(episode.source_slug)
        if episode.source_slug in refresh.open:
            opened += open_up(s, episode)
        if details is None and access is None:
            continue
        if episode.removed_from_source:
            episode.removed_from_source = False
            returned += 1
        if access is not None and episode.access_refused_at is None:
            lock_refused(episode, access)
        if details is not None:
            updated += apply_refreshed_details(episode, details)
            check_upgrades_after_refresh(s, episode)
    if opened:
        dispatch_queued_media_download_operations(s)
    return RefreshCounts(updated=updated, removed=removed, returned=returned)
