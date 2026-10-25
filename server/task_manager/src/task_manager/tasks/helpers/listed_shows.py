"""Index the episodes of a show whose Source lists them (``Feature.EPISODE_LISTS``).

VODLoft keeps the seasons and episode numbers of a Source that has them: S02E05.
A Source without seasons gets one season per upload year, with the episodes in
each year numbered by upload date: S2024E01, S2024E02. A new episode is numbered
after the episodes VODLoft already has, so existing file names never change.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Episode, Season, Show
from backend.services.seasons import create_season_record
from backend.types.episode_types import EpisodePublishStatus
from backend.types.media_types import MediaType
from backend.utils.helpers import generate_uuid
from sources import Source, VideoDetails
from .episodes.events import queue_episode_status_events

SOURCE_SLUG_META_KEY = "source.slug"


def _source_slug(episode: Episode) -> str:
    return episode.get_meta(SOURCE_SLUG_META_KEY) or episode.slug


def _season_number(details: VideoDetails, fallback: datetime) -> int:
    if details.season is not None:
        return details.season.number
    return (details.published_at or fallback).year


def _order_key(details: VideoDetails, fallback: datetime):
    number = details.episode_number if details.episode_number is not None else 10**9
    return _season_number(details, fallback), number, details.published_at or fallback, details.slug


def _episode_number(s: Session, season: Season, wanted: int | None) -> int:
    """The Source's own episode number, unless the season already has an episode with it."""
    taken = set()
    for identifier in s.scalars(select(Episode.episode_identifier).where(Episode.season_id == season.id)):
        number = (identifier or "").rpartition("E")[2]
        if number.isdigit():
            taken.add(int(number))
    if wanted is not None and wanted not in taken:
        return wanted
    return max(taken, default=0) + 1


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
    episodes = s.scalars(select(Episode).where(Episode.show_id == show.id)).all()
    return frozenset(_source_slug(episode) for episode in episodes)


def index_listed_show(s: Session, *, show_id: int, source: Source) -> int:
    """Add the show's new episodes. Returns how many were added."""
    show = s.get(Show, show_id)
    if show is None:
        return 0
    url, known = show.sharing_url, known_episode_slugs(s, show)
    # No transaction stays open while the Source looks videos up.
    s.rollback()
    found = list(source.list_episodes(url, known=known))
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

    seasons = {season.season_number: season for season in show.seasons}
    next_index = (s.scalar(select(func.max(Episode.index)).where(Episode.show_id == show.id)) or 0) + 1
    created: list[Episode] = []
    for details in ordered:
        number = _season_number(details, now)
        season = seasons.get(number)
        if season is None:
            ref = details.season
            season = create_season_record(
                s, show_id=show.id, index=max((x.index for x in show.seasons), default=0) + 1,
                slug=ref.slug if ref else str(number),
                name=(ref.title or f"Season {number}") if ref else str(number),
                season_number=number, update_show_profiles=True,
            )
            seasons[number] = season
            s.refresh(show)
        episode_number = _episode_number(s, season, details.episode_number if details.season else None)
        episode = Episode(
            uuid=generate_uuid(),
            type=MediaType.EPISODE.value,
            source_key=show.source_key,
            show_id=show.id,
            season_id=season.id,
            index=next_index,
            episode_identifier=f"ep.S{number:02d}E{episode_number:02d}",
            slug=_episode_slug(s, show, details.slug),
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
        )
        episode.set_meta(SOURCE_SLUG_META_KEY, details.slug)
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
