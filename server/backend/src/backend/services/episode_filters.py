"""Which episodes a Download Profile downloads: one ordered list of filters.

The filters are applied from top to bottom, each to what the filters above it let
through. Before the first one, the Collection's indexed episodes that cannot be
downloaded at all are left out (not published yet, DRM, gone from the Source, or
behind a subscription VODLoft is not signed in with).

- Only download keeps the episodes that match; Skip leaves them out.
- A date line (published or downloaded) narrows like Only download. "The latest 25"
  takes the 25 newest of what reaches it.
- Keep never leaves anything out. It protects matching downloads from being deleted,
  wherever it stands in the list.

Only a date line deletes. With delete older episodes on, a download is removed when an
Only download date line leaves its episode out, unless a Keep filter or a person kept
it, or the Source no longer has the episode and the Home page still asks whether to keep
it. Changing the other filters never deletes anything.

Everything that asks which episodes a profile wants uses this module: the Download
Profile worker and its cleanup, the counts in the profile form, Skipped by filter,
the feeds and Local Media Profile moves. The walk runs in Python over the
Collection's episodes, because title and description filters use regular
expressions with a timeout.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional, Protocol, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.db.models import Collection, DownloadProfile, DownloadProfileFilter, Episode
from backend.services.media_access import AccessLocks
from backend.services.removed_downloads import awaits_keep_answer
from backend.services.regex_check import PatternError, compile_pattern, search, split_inline_ignore_case
from backend.types.download_profile_types import (
    DATE_FIELDS,
    DownloadKeptBy,
    DurationOperator,
    EpisodeFilterAction,
    EpisodeFilterField,
    MediaDownloadArtifactStatus,
)
from backend.types.episode_types import EpisodePublishStatus
from config import get_settings


class EpisodeFilter(Protocol):
    """A filter as stored, or as typed into a form that is not saved yet."""

    action: str
    field: str
    pattern: Optional[str]
    duration_operator: Optional[str]
    duration_seconds: Optional[int]
    episode_types: Optional[list[str]]
    season_slugs: Optional[list[str]]
    include_upcoming: bool
    days: Optional[int]
    count: Optional[int]
    starting_from: Optional[date]


@dataclass(frozen=True)
class EpisodeSelection:
    """What a Download Profile asks for: a saved profile, or the form being edited."""

    collection: Collection
    download_with_countdown: bool
    filters: Sequence[EpisodeFilter] = field(default_factory=tuple)

    @classmethod
    def of_profile(cls, profile: DownloadProfile) -> "EpisodeSelection":
        return cls(
            collection=profile.collection,
            download_with_countdown=profile.download_with_countdown,
            filters=list(profile.filters),
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_date_line(item: EpisodeFilter) -> bool:
    return item.field in DATE_FIELDS


def published_at(episode: Episode) -> Optional[datetime]:
    return episode.published_date or episode.went_live_date


def _episode_type(episode: Episode) -> Optional[str]:
    # The identifier's type tag, without parsing the rest of it.
    identifier = episode.episode_identifier or ""
    episode_type, separator, _rest = identifier.partition(".")
    return episode_type if separator else None


def filter_matches(item: EpisodeFilter, episode: Episode) -> Optional[bool]:
    """Whether the episode is what a filter that is not a date line describes; None when it cannot tell.

    A duration filter cannot tell for an episode whose length is not known yet. A
    pattern that runs out of time counts as not matching, like in the tester.
    """
    if item.field == EpisodeFilterField.TYPES:
        return _episode_type(episode) in (item.episode_types or ())
    if item.field == EpisodeFilterField.SEASONS:
        return episode.season is not None and episode.season.slug in (item.season_slugs or ())
    if item.field == EpisodeFilterField.DURATION:
        duration = episode.duration or 0
        if duration <= 0 or not item.duration_seconds:
            return None
        if item.duration_operator == DurationOperator.SHORTER:
            return duration < item.duration_seconds
        return duration > item.duration_seconds
    try:
        compiled = compile_pattern(*split_inline_ignore_case(item.pattern or "", False))
    except PatternError:
        return False
    text = episode.title if item.field == EpisodeFilterField.TITLE else episode.description
    return bool(search(compiled, text))


def _leaves_out(item: EpisodeFilter, episode: Episode) -> bool:
    """Whether a Skip or Only download filter that is not a date line leaves the episode out."""
    matched = filter_matches(item, episode)
    if matched is None:
        # An episode the filter cannot judge is not left out by it.
        return False
    return matched if item.action == EpisodeFilterAction.SKIP else not matched


def _cutoff(days: int, now: datetime) -> datetime:
    return now - timedelta(days=days)


def _local_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(get_settings().timezone)).astimezone(timezone.utc)


def _in_date_line(item: EpisodeFilter, episodes: Sequence[Episode], now: datetime) -> set[int]:
    """The ids of the episodes, newest first, that a date line lets through."""
    if item.field == EpisodeFilterField.PUBLISHED and item.count:
        return {episode.id for episode in episodes[:item.count]}
    if item.days:
        cutoff = _cutoff(item.days, now)
        # An episode with no publication instant is not left out by the days alone.
        return {
            episode.id for episode in episodes
            if (moment := published_at(episode)) is None or moment >= cutoff
        }
    if item.field == EpisodeFilterField.PUBLISHED and item.starting_from is not None:
        start = _local_start(item.starting_from)
        return {episode.id for episode in episodes if (moment := published_at(episode)) is not None and moment >= start}
    return {episode.id for episode in episodes}


def _available(selection: EpisodeSelection, episode: Episode, locks: AccessLocks, *, at_source: bool = False) -> bool:
    eligible = {EpisodePublishStatus.PUBLISHED_FINAL.value}
    if selection.download_with_countdown:
        eligible.add(EpisodePublishStatus.PUBLISHED_PRELIMINARY.value)
    return (
        episode.publish_status in eligible
        # Media protected by DRM cannot be downloaded, nor can media the Source no longer has.
        and not episode.drm_protected
        and (at_source or not episode.removed_from_source)
        # Nor can media locked behind an access VODLoft does not have, such as a channel membership.
        and not locks.locked(episode)
    )


def _newest_first(episodes: Iterable[Episode]) -> list[Episode]:
    # A query result can only be read once, and it is read twice below.
    episodes = list(episodes)
    dated = [episode for episode in episodes if published_at(episode) is not None]
    undated = [episode for episode in episodes if published_at(episode) is None]
    dated.sort(key=lambda episode: (published_at(episode), episode.id), reverse=True)
    undated.sort(key=lambda episode: episode.id, reverse=True)
    return dated + undated


def collection_episodes(s: Session, collection_id: int) -> list[Episode]:
    """Every indexed episode of the Collection, newest first."""
    return _newest_first(s.scalars(
        select(Episode).where(Episode.collection_id == collection_id).options(selectinload(Episode.season))
    ))


@dataclass
class Evaluation:
    """What the filters do with each of the Collection's indexed episodes."""

    filters: Sequence[EpisodeFilter]
    total: int
    unavailable: int
    counts: list[int]
    """How many episodes each filter leaves out; always 0 for Keep."""
    wanted: list[Episode]
    """The episodes the profile downloads, newest first."""
    left_out_by: dict[int, str]
    """Episode id -> unavailable, or filter:<index> for the filter that left it out."""
    reached: list[set[int]]
    """Per filter, the ids of the episodes that reached it."""
    kept: set[int]
    """Episodes whose downloads a Keep filter protects."""
    keep_downloaded_since: list[datetime]
    """A Keep filter on the downloaded date protects downloads downloaded since each of these."""
    removed_from_source: set[int] = field(default_factory=set)
    """Episodes the Source no longer has: their downloads wait for the person's keep answer."""
    as_if_at_source: Optional["Evaluation"] = None
    """The same walk with those episodes still at the Source. Retention judges their downloads by it
    once the person chose not to keep them, so the date lines apply to them as before."""

    def left_out_by_filter(self, episode_id: int) -> Optional[int]:
        reason = self.left_out_by.get(episode_id, "")
        return int(reason[len("filter:"):]) if reason.startswith("filter:") else None


def evaluate(
        s: Session,
        selection: EpisodeSelection,
        *,
        episodes: Optional[Sequence[Episode]] = None,
        now: Optional[datetime] = None,
) -> Evaluation:
    """Walk the filters over the Collection's indexed episodes."""
    now = now or _utc_now()
    episodes = collection_episodes(s, selection.collection.id) if episodes is None else episodes
    locks = AccessLocks()
    evaluation = _walk(selection, episodes, locks, now, at_source=False)
    if evaluation.removed_from_source:
        evaluation.as_if_at_source = _walk(selection, episodes, locks, now, at_source=True)
    return evaluation


def _walk(
        selection: EpisodeSelection, episodes: Sequence[Episode], locks: AccessLocks, now: datetime, *, at_source: bool,
) -> Evaluation:
    filters = list(selection.filters)

    left_out_by: dict[int, str] = {}
    remaining: list[Episode] = []
    for episode in episodes:
        if _available(selection, episode, locks, at_source=at_source):
            remaining.append(episode)
        else:
            left_out_by[episode.id] = "unavailable"
    available = list(remaining)

    counts = [0] * len(filters)
    reached: list[set[int]] = []
    kept: set[int] = set()
    keep_downloaded_since: list[datetime] = []
    for index, item in enumerate(filters):
        reached.append({episode.id for episode in remaining})
        if item.action == EpisodeFilterAction.KEEP:
            if item.field == EpisodeFilterField.DOWNLOADED:
                if item.days:
                    keep_downloaded_since.append(_cutoff(item.days, now))
            elif is_date_line(item):
                kept |= _in_date_line(item, available, now)
            else:
                kept |= {episode.id for episode in episodes if filter_matches(item, episode) is True}
            continue
        if is_date_line(item):
            through = _in_date_line(item, remaining, now)
            leaves = [episode for episode in remaining if episode.id not in through]
        else:
            leaves = [episode for episode in remaining if _leaves_out(item, episode)]
        if not leaves:
            continue
        gone = {episode.id for episode in leaves}
        for episode_id in gone:
            left_out_by[episode_id] = f"filter:{index}"
        counts[index] = len(gone)
        remaining = [episode for episode in remaining if episode.id not in gone]

    return Evaluation(
        filters=filters,
        total=len(episodes),
        unavailable=len(episodes) - len(available),
        counts=counts,
        wanted=remaining,
        left_out_by=left_out_by,
        reached=reached,
        kept=kept,
        keep_downloaded_since=keep_downloaded_since,
        removed_from_source={episode.id for episode in episodes if episode.removed_from_source},
    )


def wanted_episodes(s: Session, selection: EpisodeSelection, *, only_episode_id: Optional[int] = None) -> list[Episode]:
    """Episodes the profile downloads, newest first."""
    wanted = evaluate(s, selection).wanted
    if only_episode_id is not None:
        return [episode for episode in wanted if episode.id == only_episode_id]
    return wanted


def _judged_by(evaluation: Evaluation, download) -> Evaluation:
    """A download of an episode the Source no longer has is judged as if the episode were still there."""
    if download.media_item_id in evaluation.removed_from_source and evaluation.as_if_at_source is not None:
        return evaluation.as_if_at_source
    return evaluation


def kept_by(evaluation: Evaluation, download) -> Optional[DownloadKeptBy]:
    """What keeps a download safe from deletion, if anything: a person, a Keep filter, or the
    Home page asking whether to keep it because its episode left the Source."""
    evaluation = _judged_by(evaluation, download)
    if download.kept:
        return DownloadKeptBy.HAND
    if download.media_item_id in evaluation.kept:
        return DownloadKeptBy.KEEP_FILTER
    if awaits_keep_answer(download, removed_from_source=download.media_item_id in evaluation.removed_from_source):
        return DownloadKeptBy.KEEP_QUESTION
    if download.downloaded_at is not None and any(
        download.downloaded_at >= since for since in evaluation.keep_downloaded_since
    ):
        return DownloadKeptBy.KEEP_FILTER
    return None


def protected(evaluation: Evaluation, download) -> bool:
    """Whether a download is safe from deletion."""
    return kept_by(evaluation, download) is not None


def date_line_leaves_out(evaluation: Evaluation, download, *, now: Optional[datetime] = None) -> bool:
    """Whether an Only download date line leaves this download out, so that retention deletes it.

    A published line leaves out what it does not let through; "published since" never
    deletes. A downloaded line deletes a download that reached it, N days after downloading.
    """
    now = now or _utc_now()
    evaluation = _judged_by(evaluation, download)
    episode_id = download.media_item_id
    for index, item in enumerate(evaluation.filters):
        if item.action != EpisodeFilterAction.ONLY or not is_date_line(item):
            continue
        if item.field == EpisodeFilterField.DOWNLOADED:
            if (
                item.days and episode_id in evaluation.reached[index]
                and download.downloaded_at is not None and download.downloaded_at < _cutoff(item.days, now)
            ):
                return True
        elif (item.count or item.days) and evaluation.left_out_by.get(episode_id) == f"filter:{index}":
            return True
    return False


def filter_leaving_out(evaluation: Evaluation, download, *, now: Optional[datetime] = None) -> Optional[int]:
    """The index of the filter that leaves this download out of the profile, if one does.

    Any Skip or Only download filter counts here, unlike for retention. A downloaded line
    leaves a download out N days after downloading, not by its publication date. An
    episode that cannot be downloaded at all is not left out by a filter.
    """
    now = now or _utc_now()
    evaluation = _judged_by(evaluation, download)
    index = evaluation.left_out_by_filter(download.media_item_id)
    if index is not None and evaluation.filters[index].field != EpisodeFilterField.DOWNLOADED:
        return index
    for index, item in enumerate(evaluation.filters):
        if (
            item.action == EpisodeFilterAction.ONLY and item.field == EpisodeFilterField.DOWNLOADED and item.days
            and download.media_item_id in evaluation.reached[index]
            and download.downloaded_at is not None and download.downloaded_at < _cutoff(item.days, now)
        ):
            return index
    return None


def left_out_by_date_line(evaluation: Evaluation, episode_id: int) -> bool:
    index = evaluation.left_out_by_filter(episode_id)
    return index is not None and is_date_line(evaluation.filters[index])


def retention_removes(evaluation: Evaluation, download, *, delete_older_episodes: bool) -> bool:
    """Whether the profile's cleanup removes this download of its own.

    A download that is not on disk yet goes as soon as a date line leaves its episode
    out. One that is, only when the profile deletes older episodes.
    """
    if protected(evaluation, download):
        return False
    if download.artifact_status == MediaDownloadArtifactStatus.ABSENT.value and left_out_by_date_line(
        evaluation, download.media_item_id,
    ):
        return True
    return delete_older_episodes and date_line_leaves_out(evaluation, download)


def has_latest_count(filters: Iterable[EpisodeFilter]) -> bool:
    """Whether a date line downloads the latest N episodes, so a new episode can push an older one out."""
    return any(
        item.action == EpisodeFilterAction.ONLY and item.field == EpisodeFilterField.PUBLISHED and item.count
        for item in filters
    )


def filters_allow_new_episode(filters: Iterable[EpisodeFilter], episode: Episode) -> bool:
    """Whether a profile will download this episode once it is published, as the newest episode.

    A feed asks this for a live episode. A new episode is the newest, so it passes every
    date line; only the other Skip and Only download filters can leave it out.
    """
    return not any(
        item.action != EpisodeFilterAction.KEEP and not is_date_line(item) and _leaves_out(item, episode)
        for item in filters
    )


def add_upcoming_season(profile: DownloadProfile, slug: str) -> None:
    """A new season joins every seasons filter of the profile that includes upcoming seasons."""
    for item in profile.filters:
        if item.field == EpisodeFilterField.SEASONS and item.include_upcoming and slug not in (item.season_slugs or []):
            item.season_slugs = [*(item.season_slugs or []), slug]


def set_profile_filters(profile: DownloadProfile, filters: Sequence[EpisodeFilter]) -> None:
    """Replace a profile's Which episodes with these filters, in this order."""
    def only(field_names: tuple[str, ...], item: EpisodeFilter, name: str):
        return getattr(item, name, None) if item.field in field_names else None

    pattern_fields = (EpisodeFilterField.TITLE, EpisodeFilterField.DESCRIPTION)
    profile.filters = [
        DownloadProfileFilter(
            position=position,
            action=str(item.action),
            field=str(item.field),
            pattern=only(pattern_fields, item, "pattern"),
            duration_operator=(
                str(item.duration_operator) if item.field == EpisodeFilterField.DURATION and item.duration_operator else None
            ),
            duration_seconds=only((EpisodeFilterField.DURATION,), item, "duration_seconds"),
            episode_types=list(item.episode_types or []) if item.field == EpisodeFilterField.TYPES else None,
            season_slugs=list(item.season_slugs or []) if item.field == EpisodeFilterField.SEASONS else None,
            include_upcoming=bool(item.include_upcoming) if item.field == EpisodeFilterField.SEASONS else False,
            days=only(DATE_FIELDS, item, "days") or None,
            count=only((EpisodeFilterField.PUBLISHED,), item, "count") or None,
            starting_from=only((EpisodeFilterField.PUBLISHED,), item, "starting_from"),
        )
        for position, item in enumerate(filters)
    ]
