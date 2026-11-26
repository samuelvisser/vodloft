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

A collection of a whole channel, on a Site with ``link_seasons``, can make the
channel's playlists, or an artist's albums, its link seasons: every one, or the
ones the user keeps on. A link season only takes videos the collection itself
lists, unless it adds the others too, so a video of another channel in it stays
out. The collection lists only the feeds of its channel it takes, and a video of
a feed it no longer takes leaves, unless a link season keeps it. A video in a link
season goes to that season, and a video in several of them to the one that comes
first. A video in none goes to the channel season, or to its season per year, as the
collection is set; a channel season that holds the whole channel has every video
of its feeds, also those of a link season. Once a video has a file it stays where it is,
until the user moves it.

A collection of one list, such as a playlist or an album, has that list as its
one season, and numbers its videos in the list's order. Each collection checks
for duplicates among its own episodes only: another collection may have the same
video.

A collection that splits videos by chapter, at a Source with ``Feature.CHAPTERS``,
adds each new video with chapters as a season of its own, named after the video,
with an episode per chapter. Each part is downloaded on its own, as just its stretch
of the video, and otherwise is an episode like any other. A part stays where it is,
and keeps its own title and length.

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
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Collection, Episode, Season
from backend.db.core import run_write_transaction
from backend.services.media_access import lock_refused
from backend.types.season_types import SeasonOrigin
from backend.services.notifications.emitters import link_seasons_found
from backend.services.season_order import arrange_seasons
from backend.services.source_options import ytdlp_call_options
from backend.services.sites import collection_site
from backend.services.link_seasons import (
    SeasonFinder, SeasonNumbers, holds_only_link_seasons, list_lists, lists_own_link, made_from_list, own_feeds, section_list_names, place_in_link_seasons, link_seasons_on,
    save_lists,
)
from backend.services.metadata_refresh import new_item_metadata_is_final
from backend.services.pending_episodes import site_follows_pending
from backend.services.removed_downloads import back_at_source, left_source
from backend.types.episode_types import PENDING_EPISODE_PUBLISH_STATUSES, EpisodePublishStatus
from backend.types.media_types import MediaType
from backend.types.collection_types import EpisodeIdentifier
from backend.utils.helpers import generate_uuid
from sources import MAIN_TAG, Chapter, Feature, ItemRef, SeasonRef, Source, VideoDetails, get_source, site_for
from .episodes.events import queue_episode_status_events
from .episodes.identifier import next_identifier
from .general import datetime_to_string
from .progress import update_progress
from task_manager.tasks.media_download_operations import dispatch_queued_media_download_operations
from .locked_media import open_up
from .refreshed_metadata import apply_refreshed_details, check_upgrades_after_refresh

logger = logging.getLogger(__name__)

_LISTING_PROGRESS = 10
_PLAYLISTS_PROGRESS = 60
_SAVING_PROGRESS = 90


def _season_number(details: VideoDetails, fallback: datetime) -> int:
    if details.season is not None:
        return details.season.number
    return (details.published_at or fallback).year


def _order_key(details: VideoDetails, fallback: datetime):
    number = details.episode_number if details.episode_number is not None else 10**9
    return _season_number(details, fallback), number, details.published_at or fallback, details.slug


def _identifier(
    collection: Collection, season: Season, details: VideoDetails, identifiers: set[str], numbers: SeasonNumbers,
    fallback: datetime,
) -> str:
    if details.tag != MAIN_TAG:
        return next_identifier(identifiers, details.tag)
    match EpisodeIdentifier(collection.episode_identifier):
        case EpisodeIdentifier.DATE_BASED:
            identifier = f"ep.{datetime_to_string(details.published_at or fallback)}"
            # Two videos uploaded at the same moment: the second one is auxiliary.
            return next_identifier(identifiers, "aux") if identifier in identifiers else identifier
        case EpisodeIdentifier.NUMBERED:
            return next_identifier(identifiers, "ep")
        case EpisodeIdentifier.SEASONAL:
            number = numbers.take(season, details.episode_number if details.season else None)
            return f"ep.S{season.season_number:02d}E{number:02d}"


def _episode_slug(s: Session, collection: Collection, source_slug: str) -> str:
    """The Source's own slug, unless an episode of another collection already has it."""
    taken = s.scalar(select(func.count()).select_from(Episode).where(Episode.slug == source_slug))
    return f"{collection.slug}-{source_slug}" if taken else source_slug


def adds_pending(collection: Collection) -> bool:
    """Whether upcoming and live videos of the collection are added before they are published."""
    return get_source(collection.source_key).has(Feature.PENDING_CHECKS) and site_follows_pending(collection.site_key)


def known_episode_slugs(s: Session, collection: Collection) -> frozenset[str]:
    """The videos the collection has."""
    return frozenset(s.scalars(select(Episode.video_slug).where(Episode.collection_id == collection.id)))


def splits_chapters(collection: Collection) -> bool:
    """Whether the collection splits its new videos by chapter."""
    return collection.split_chapters and get_source(collection.source_key).has(Feature.CHAPTERS)


def with_chapters(source: Source, details: VideoDetails) -> VideoDetails:
    """A listed video with its chapters, looked up when the listing did not say."""
    if details.chapters is not None or details.publish_status in PENDING_EPISODE_PUBLISH_STATUSES:
        return details
    try:
        found = source.video_details(details.url)
    except Exception as exc:
        logger.info("Adding %s whole, because its chapters could not be looked up: %s", details.url, exc)
        return details
    return replace(details, chapters=found.chapters or ())


def _list_new_episodes(s: Session, collection: Collection, source: Source, progress) -> list[VideoDetails]:
    title, url = collection.title, collection.sharing_url
    if url is None or not lists_own_link(collection):
        # Its link seasons say what it holds, so its own link is not listed.
        return []
    feeds = own_feeds(collection)
    split = splits_chapters(collection)
    known = known_episode_slugs(s, collection)
    # No transaction stays open while the Source looks videos up.
    s.rollback()
    update_progress(progress, _LISTING_PROGRESS, f"Listing the episodes of '{title}' at {source.name}")
    found: list[VideoDetails] = []
    for details in source.list_episodes(url, known=known, feeds=feeds):
        found.append(with_chapters(source, details) if split else details)
        message = f"Found {len(found)} new {'episode' if len(found) == 1 else 'episodes'} of '{title}' at {source.name}"
        if progress:
            # A Source can't say how many episodes there are, so the count is shown instead of a percentage.
            progress.set(_LISTING_PROGRESS, message, meta={"found": len(found)})
        else:
            update_progress(progress, _LISTING_PROGRESS, message)
    return found


def index_listed_collection(
    s: Session, *, collection_id: int, source: Source, progress=None, dry_run: bool = False, by_user: bool = False,
) -> int:
    """Add the collection's new episodes, and put its videos in the seasons of the playlists that are seasons.
    Returns how many episodes were added, or would be added in a dry run. ``by_user`` says the user's own change
    asked for this listing, so the downloaded videos that leave the collection go with their files, as the user
    was told, rather than waiting for the Home page."""
    collection = s.get(Collection, collection_id)
    if collection is None:
        return 0
    with ytdlp_call_options(source, *collection.ytdlp_option_texts, session=s):
        return _index_listed_collection(
            s, collection_id=collection_id, source=source, progress=progress, dry_run=dry_run, by_user=by_user,
        )


def _index_listed_collection(s: Session, *, collection_id: int, source: Source, progress, dry_run: bool, by_user: bool) -> int:
    collection = s.get(Collection, collection_id)
    if collection is None:
        return 0
    title = collection.title
    found = _list_new_episodes(s, collection, source, progress)
    s.rollback()
    if dry_run:
        for details in found:
            logger.info("Dry run: would add %s (%s)", details.slug, details.title)
        return len(found)
    collection = s.get(Collection, collection_id)
    listing = None
    if collection is not None and link_seasons_on(collection):
        # The Site's own word for its lists, such as playlists on YouTube or albums on Bandcamp.
        lists = section_list_names(collection).plural
        update_progress(progress, _PLAYLISTS_PROGRESS, f"Listing the {lists} of '{title}' at {source.name}")
        listing = list_lists(s, collection, source, also=frozenset(details.slug for details in found))
    s.rollback()
    if found:
        update_progress(progress, _SAVING_PROGRESS, f"Saving {len(found)} new episodes of '{title}'")

    outside = listing.outside if listing is not None else []
    if outside:
        update_progress(progress, _SAVING_PROGRESS, f"Saving {len(outside)} videos of the {lists} of '{title}'")

    def save(w: Session) -> int:
        collection = w.get(Collection, collection_id)
        if collection is not None and listing is not None:
            link_seasons_found(w, collection, save_lists(w, collection, listing))
        added = add_listed_episodes(
            w, collection_id=collection_id, found=[*found, *outside], sources=listing.sources if listing is not None else None,
        )
        if outside:
            # The collection's own link does not list them, so they leave when no playlist that is a season does.
            for episode in w.scalars(select(Episode).where(
                Episode.collection_id == collection_id, Episode.video_slug.in_([details.slug for details in outside]),
            )):
                episode.from_link_season = True
            # Placing them reads the flag back, so another creator's video goes to its playlist's season only, not to
            # the channel season as a video of the channel's own.
            w.flush()
        if collection is None:
            return added
        place_in_link_seasons(w, collection, by_user=by_user)
        return added

    return run_write_transaction(save)


class _Placer(SeasonFinder):
    """Finds the season each new video goes to, and the identifier it gets there."""

    def __init__(self, s: Session, collection: Collection, now: datetime):
        super().__init__(s, collection, now)
        self.identifiers = set(s.scalars(select(Episode.episode_identifier).where(Episode.collection_id == collection.id)))

    def season(self, ref: SeasonRef | None, published_at: datetime | None, tag: str | None = None) -> Season:
        """The Source's own season, or where a new video of the feed with episode ``tag`` goes (``home_season``)."""
        if ref is None:
            return self.home_season(published_at, tag)
        season = self._by_slug.get(ref.slug)
        if season is not None and season.season_number != ref.number:
            # A season picked when the collection was added, before VODLoft knew its number.
            season.season_number = ref.number
        if season is None:
            season = self.create(slug=ref.slug, name=ref.name, number=ref.number, origin=SeasonOrigin.SITE)
        return season

    def part_identifier(self, season: Season, details: VideoDetails, number: int) -> str:
        """A part's identifier: its chapter's number in its video's season, whatever the collection's numbering, so the
        parts of one video never share a date or a number. A Short or another tag counts on its own as always."""
        if details.tag != MAIN_TAG:
            identifier = next_identifier(self.identifiers, details.tag)
        else:
            identifier = f"ep.S{season.season_number:02d}E{self.numbers.take(season, number):02d}"
        self.identifiers.add(identifier)
        return identifier

    def identifier(self, season: Season, details: VideoDetails) -> str:
        identifier = _identifier(self._collection, season, details, self.identifiers, self.numbers, self._now)
        self.identifiers.add(identifier)
        return identifier


def _new_episode(
    s: Session, collection: Collection, season: Season, index: int, identifier: str,
    details: VideoDetails, *, part: tuple[int, Chapter] | None = None, source_key: str | None = None,
) -> Episode:
    """A listed video as an episode, or with ``part``, the chapter of it with that number. ``source_key`` is the
    Source that found it, when that is not the collection's: the one of the list it is in."""
    number, chapter = part if part is not None else (None, None)
    source_key = source_key or collection.source_key
    source_slug = details.slug if chapter is None else f"{details.slug}-part-{number}"
    # A collection of links from several Sites follows each video's own Site, as does a video of a list on another Site.
    own_site = holds_only_link_seasons(collection) or source_key != collection.source_key
    site = site_for(details.url, source_key) if own_site else collection_site(collection)
    return Episode(
        uuid=generate_uuid(),
        type=MediaType.EPISODE.value,
        source_key=source_key,
        collection_id=collection.id,
        season_id=season.id,
        index=index,
        episode_identifier=identifier,
        slug=_episode_slug(s, collection, source_slug),
        source_slug=source_slug,
        publish_status=details.publish_status.value,
        # The metadata refresh sweep follows a new upload for a while, from when it is published; an older one is done.
        # A part keeps the title and length of its chapter, so a refresh of the whole video has nothing for it.
        metadata_is_final=chapter is not None or (
            details.publish_status not in PENDING_EPISODE_PUBLISH_STATUSES and new_item_metadata_is_final(
                source_key=source_key,
                site_key=site.key if own_site else collection.site_key,
                published_at=details.published_at,
            )
        ),
        scheduled_date=details.scheduled_at,
        sharing_url=details.url,
        published_date=details.published_at,
        title=site.episode_title(details.title, details.description) if chapter is None else chapter.title,
        description=details.description,
        duration=(details.duration or 0.0) if chapter is None else chapter.end - chapter.start,
        author_name=details.author_name,
        thumbnail_landscape_path=details.image_url,
        background_image_path=details.image_url,
        drm_protected=details.drm_protected,
        access=details.access,
        part_of=None if chapter is None else details.slug,
        part_start=None if chapter is None else chapter.start,
        part_end=None if chapter is None else chapter.end,
    )


def add_listed_episodes(
    s: Session, *, collection_id: int, found: list[VideoDetails], sources: Mapping[str, str] | None = None,
) -> int:
    """Save episodes the collection's Source listed, numbered after the ones the collection has. ``sources`` names the
    Source of each video another Source found, by its slug, such as a video of a list on another Site. Returns how
    many were added.

    ``s`` is a write transaction's session."""
    if not found:
        return 0
    collection = s.get(Collection, collection_id)
    if collection is None:
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

    known = set(s.scalars(select(Episode.video_slug).where(Episode.collection_id == collection.id, Episode.video_slug.in_(listed))))
    new = [details for slug, details in listed.items() if slug not in known]
    # A collection made from one list numbers its videos in the list's order, as an album numbers its tracks.
    ordered = new if made_from_list(collection) else sorted(new, key=lambda details: _order_key(details, now))

    placer = _Placer(s, collection, now)
    split = splits_chapters(collection)
    next_index = (s.scalar(select(func.max(Episode.index)).where(Episode.collection_id == collection.id)) or 0) + 1
    created: list[tuple[Episode, EpisodePublishStatus]] = []
    for details in ordered:
        chapters = details.chapters or ()
        if split and len(chapters) > 1 and details.publish_status not in PENDING_EPISODE_PUBLISH_STATUSES:
            season = placer.own_season(details.title)
            episodes = [
                _new_episode(
                    s, collection, season, next_index + offset, placer.part_identifier(season, details, number), details,
                    part=(number, chapter), source_key=(sources or {}).get(details.slug),
                )
                for offset, (number, chapter) in enumerate(enumerate(chapters, start=1))
            ]
        else:
            # A video of a list, rather than of the channel's feeds, is placed in its list's season afterwards.
            own = details.slug not in (sources or {})
            season = placer.season(details.season, details.published_at, details.tag if own else None)
            episodes = [_new_episode(
                s, collection, season, next_index, placer.identifier(season, details), details,
                source_key=(sources or {}).get(details.slug),
            )]
        for episode in episodes:
            s.add(episode)
            s.flush()
            created.append((episode, details.publish_status))
        next_index += len(episodes)

    s.flush()
    arrange_seasons(s, collection)
    for episode, status in created:
        queue_episode_status_events(
            s, episode=episode, collection=collection, old_status=None, new_status=status, was_created=True,
        )
    return len(created)


@dataclass(frozen=True)
class RefreshCounts:
    updated: int = 0
    removed: int = 0
    returned: int = 0


def refresh_listed_collection(s: Session, *, collection_id: int, source: Source) -> RefreshCounts:
    """Bring the collection's episodes up to date with what the Source says about them now.

    File names never change, so a new title only shows in VODLoft and in files
    downloaded from now on.
    """
    collection = s.get(Collection, collection_id)
    if collection is None:
        return RefreshCounts()
    with ytdlp_call_options(source, *collection.ytdlp_option_texts, session=s):
        return _refresh_listed_collection(s, collection, source)


def _refresh_listed_collection(s: Session, collection: Collection, source: Source) -> RefreshCounts:
    collection_id, title, url = collection.id, collection.title, collection.sharing_url
    # A collection that only holds its link seasons has no listing of its own to read its videos from.
    one_by_one = url is None or not lists_own_link(collection)
    # The parts of a split video are asked about once, as their video.
    items = list({
        slug: ItemRef(slug, item_url or "")
        for slug, item_url in s.execute(
            select(Episode.video_slug, Episode.sharing_url)
            .where(Episode.collection_id == collection_id, Episode.source_slug.is_not(None))
        )
    }.values())
    # No transaction stays open while the Source looks videos up.
    s.rollback()
    if not items:
        return RefreshCounts()
    refresh = source.refresh_metadata(items) if one_by_one else source.refresh_items(url, items)
    slugs = frozenset(item.slug for item in items)
    counts = run_write_transaction(lambda w: _apply_refresh(w, collection_id, refresh, slugs))
    if counts.removed or counts.returned:
        logger.info("'%s': %d episodes no longer at the Source, %d back", title, counts.removed, counts.returned)
    return counts


def _apply_refresh(s: Session, collection_id: int, refresh, slugs: frozenset[str]) -> RefreshCounts:
    updated = removed = returned = opened = 0
    for episode in list(s.scalars(select(Episode).where(Episode.collection_id == collection_id, Episode.video_slug.in_(slugs)))):
        slug = episode.video_slug
        if slug in refresh.removed:
            if not episode.removed_from_source:
                removed += 1
            # One with files stays, marked removed; one without goes.
            left_source(s, episode)
            continue
        details = refresh.details.get(slug)
        access = refresh.refused.get(slug)
        if slug in refresh.open:
            opened += open_up(s, episode)
        if details is None and access is None:
            continue
        if back_at_source(episode):
            returned += 1
        if access is not None and episode.access_refused_at is None:
            lock_refused(episode, access)
        if details is not None and episode.part_of is None:
            # A part keeps its chapter's title and length; the whole video's are not its own.
            updated += apply_refreshed_details(episode, details)
            check_upgrades_after_refresh(s, episode)
    if opened:
        dispatch_queued_media_download_operations(s)
    return RefreshCounts(updated=updated, removed=removed, returned=returned)
