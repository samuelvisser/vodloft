"""Example episodes of a collection that is being added, kept in memory and never saved.

While a collection is added, the form helpers (the output template preview, the regex
test and the Which episodes counts) have no indexed episodes to show. The Source's
cheapest lookup gives the collection's newest ones instead. VODLoft keeps them in memory
for a while, and works with them in a scratch database that lives in memory only and is
emptied again after each use, so the helpers run the same code they run for saved episodes.

Some values are only known once every episode is indexed, because VODLoft counts them from
the oldest episode. An example leaves those out, and the helpers show their names instead.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.db.core import Base, load_database_models
from backend.db.models import Collection, Episode, Season
from backend.types.collection_types import EpisodeIdentifier
from backend.types.download_profile_types import EpIdType
from backend.types.episode_types import EpisodePublishStatus
from backend.types.media_types import MediaType
from backend.types.season_types import SeasonType
from backend.utils.helpers import generate_uuid
from backend.utils.output_template import episode_output_template_values
from backend.utils.season_ordering import number_initial_seasons
from sources import MAIN_TAG, Feature, VideoDetails, get_source
from task_manager.tasks.helpers.general import datetime_to_string

EXAMPLE_SOURCE_PREFIX = "new-episode:"
"""Starts the id of an example in the output template preview, which sends all of its values along."""

_CACHE_SECONDS = 15 * 60
_CACHE_SIZE = 32

# Values VODLoft numbers from the collection's oldest episode.
_INDEX_VALUES = frozenset({"episode_index"})
_SEASON_INDEX_VALUES = frozenset({"season_index"})
_IDENTIFIER_VALUES = frozenset({"episode_identifier", "episode_number", "episode_sub_number", "episode_label"})


@dataclass(frozen=True)
class ExampleSeason:
    slug: str
    name: str


@dataclass(frozen=True)
class ExampleCollection:
    """A collection as the Add collection form describes it before it is saved."""

    source_key: str
    url: str
    slug: str
    title: str
    author_name: str
    type: str
    episode_identifier: EpisodeIdentifier
    seasons: Sequence[ExampleSeason] = ()
    """The collection's own seasons, as they will be saved; none for a season per upload year."""


@dataclass(frozen=True)
class Example:
    episode: Episode
    pending: frozenset[str]
    """Template values this example cannot know, because VODLoft counts them from the oldest episode."""


_cache: OrderedDict[tuple[str, str], tuple[float, list[VideoDetails]]] = OrderedDict()
_cache_lock = threading.Lock()


def newest_episodes(source_key: str, url: str) -> list[VideoDetails]:
    """The Source's newest episodes of the collection at this link, looked up again after a while."""
    key = (source_key, url)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < _CACHE_SECONDS:
            _cache.move_to_end(key)
            return cached[1]
    found = get_source(source_key).newest_episodes(url)
    with _cache_lock:
        _cache[key] = (time.monotonic(), found)
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return found


_scratch_engine: Engine | None = None
_scratch_lock = threading.Lock()


def _scratch() -> Engine:
    """An empty VODLoft database in memory, made once. Every use rolls back what it added."""
    global _scratch_engine
    if _scratch_engine is None:
        load_database_models()
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        _scratch_engine = engine
    return _scratch_engine


@contextmanager
def example_session(collection: ExampleCollection) -> Iterator[tuple[Session, Collection, list[Example]]]:
    """The collection and its examples in the scratch database, newest first; all of it is gone afterwards."""
    videos = newest_episodes(collection.source_key, collection.url)
    with _scratch_lock:
        connection = _scratch().connect()
        transaction = connection.begin()
        session = Session(bind=connection, autoflush=False)
        try:
            saved, examples = _add(session, collection, videos)
            yield session, saved, examples
        finally:
            session.close()
            transaction.rollback()
            connection.close()


def example_template_values(example: Example) -> dict[str, str]:
    """The output template values of an example, with the ones it cannot know shown by name."""
    values = episode_output_template_values(example.episode)
    values.update({name: f"[{name}]" for name in example.pending})
    return values


def _add(s: Session, form: ExampleCollection, videos: list[VideoDetails]) -> tuple[Collection, list[Example]]:
    listed = get_source(form.source_key).has(Feature.EPISODE_LISTS)
    collection = Collection(
        uuid=generate_uuid(), source_key=form.source_key, slug=form.slug, title=form.title, sharing_url=form.url,
        membership_level="FREE", type=form.type, episode_identifier=form.episode_identifier.value,
        author_name=form.author_name, author_slug="",
    )
    s.add(collection)
    seasons: dict[str, Season] = {}
    for season_in, index, season_type, number in number_initial_seasons(list(form.seasons)):
        seasons[season_in.slug] = Season(
            collection=collection, index=index, slug=season_in.slug, name=season_in.name,
            season_type=season_type.value, season_number=number,
        )
    now = datetime.now(timezone.utc)
    counters: dict[str, int] = {}
    examples: list[Example] = []
    # Oldest first, so the scratch indices run the way indexing would number these episodes.
    unique = list({video.slug: video for video in reversed(videos)}.values())
    for position, video in enumerate(unique, start=1):
        pending = set(_INDEX_VALUES)
        season = seasons.get(video.season.slug) if video.season is not None else None
        if season is None:
            season = _year_season(collection, seasons, video, now)
            pending |= _SEASON_INDEX_VALUES
        identifier = _identifier(form.episode_identifier, listed, season, video)
        if identifier is None:
            counters[video.tag] = counters.get(video.tag, 0) + 1
            identifier = _provisional_identifier(video.tag, counters[video.tag])
            pending |= _IDENTIFIER_VALUES
        episode = Episode(
            uuid=generate_uuid(), type=MediaType.EPISODE.value, source_key=form.source_key, collection=collection, season=season,
            index=position, episode_identifier=identifier, dw_episode_number=video.number_text,
            slug=video.slug, source_slug=video.slug,
            publish_status=EpisodePublishStatus.PUBLISHED_FINAL.value, sharing_url=video.url,
            published_date=video.published_at, title=video.title, description=video.description,
            duration=video.duration or 0.0, author_name=video.author_name, thumbnail_landscape_path=video.image_url,
            drm_protected=video.drm_protected, access=video.access,
        )
        s.add(episode)
        examples.append(Example(episode=episode, pending=frozenset(pending)))
    s.add_all(seasons.values())
    s.flush()
    examples.reverse()
    return collection, examples


def _year_season(collection: Collection, seasons: dict[str, Season], video: VideoDetails, now: datetime) -> Season:
    """The season per upload year that indexing puts an episode in when the Source has no seasons."""
    year = str((video.published_at or now).year)
    if year not in seasons:
        seasons[year] = Season(
            collection=collection, index=len(seasons) + 1, slug=year, name=year,
            season_type=SeasonType.NORMAL.value, season_number=int(year),
        )
    return seasons[year]


def _identifier(numbering: EpisodeIdentifier, listed: bool, season: Season, video: VideoDetails) -> str | None:
    """The identifier indexing will give the episode, or None when it counts it from the oldest episode."""
    if listed:
        # A listed collection numbers only its main episodes by the chosen scheme.
        main = video.tag == MAIN_TAG
    else:
        # The Daily Wire: extras of an episode are dated like episodes, and an Extras season has none.
        main = season.season_type != SeasonType.EXTRA.value and (
            video.tag == MAIN_TAG or (numbering is EpisodeIdentifier.DATE_BASED and video.tag == EpIdType.EP_EXTRA)
        )
    if not main:
        return None
    if numbering is EpisodeIdentifier.DATE_BASED:
        return f"{EpIdType.EP}.{datetime_to_string(video.published_at)}" if video.published_at else None
    number = video.episode_number
    if number is None:
        return None
    if numbering is EpisodeIdentifier.SEASONAL and (not listed or video.season is not None):
        return f"{EpIdType.EP}.S{season.season_number:02d}E{number:02d}"
    if numbering is EpisodeIdentifier.NUMBERED and not listed:
        return f"{EpIdType.EP}.{number}"
    return None


def _provisional_identifier(tag: str, count: int) -> str:
    """An identifier of the right kind, so filters by episode type work; its number is not shown."""
    if tag == EpIdType.EP_EXTRA:
        return f"{EpIdType.EP_EXTRA}.other.{count}.1"
    return f"{tag}.{count}"
