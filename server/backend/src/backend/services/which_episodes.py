"""Which episodes a Download Profile downloads, line by line.

The lines of Which episodes narrow the Collection's indexed episodes one after
another: what can be downloaded at all (not shown as a line), the episode types,
the seasons of a seasonal Collection, the date window, and then your own rules.
The download worker takes the result; the profile form shows how many episodes
each line leaves out, and which.

The built-in lines run in SQL so large Collections do not load thousands of
episodes only to discard most of them. Your own rules run in Python on what is
left, since they use regular expressions with a timeout.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from backend.db.models import Collection, DownloadProfile, Episode, Season
from backend.services.episode_rules import EpisodeRule, first_rule_leaving_out
from backend.types.collection_types import EpisodeIdentifier
from backend.types.episode_types import EpisodePublishStatus
from backend.utils.episode import episode_identifier_type_predicate
from config import get_settings
from sources import UnknownSourceError, get_source


@dataclass(frozen=True)
class EpisodeSelection:
    """What a Download Profile asks for: a saved profile, or the form being edited."""

    collection: Collection
    ep_id_type_list: Sequence[str]
    download_with_countdown: bool
    download_days_in_past: int
    download_episode_count: int
    download_starting_from: Optional[date]
    season_ids: Sequence[int]
    include_upcoming_seasons: bool
    rules: Sequence[EpisodeRule] = field(default_factory=tuple)

    @classmethod
    def of_profile(cls, profile: DownloadProfile) -> "EpisodeSelection":
        return cls(
            collection=profile.collection,
            ep_id_type_list=list(profile.ep_id_type_list),
            download_with_countdown=profile.download_with_countdown,
            download_days_in_past=profile.download_days_in_past,
            download_episode_count=profile.download_episode_count,
            download_starting_from=profile.download_starting_from,
            season_ids=[season.id for season in profile.seasons],
            include_upcoming_seasons=profile.include_upcoming_seasons,
            rules=list(profile.rules),
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _subscription_active(source_key: str) -> bool:
    try:
        return get_source(source_key).subscription_active
    except UnknownSourceError:
        return False


def _published_at():
    return func.coalesce(Episode.published_date, Episode.went_live_date)


def _availability(selection: EpisodeSelection, stmt: Select) -> Select:
    eligible_statuses = [EpisodePublishStatus.PUBLISHED_FINAL]
    if selection.download_with_countdown:
        eligible_statuses.append(EpisodePublishStatus.PUBLISHED_PRELIMINARY)
    stmt = stmt.where(
        Episode.publish_status.in_(eligible_statuses),
        # Media protected by DRM cannot be downloaded.
        Episode.drm_protected.is_(False),
        # Nor can media the Source no longer has.
        Episode.removed_from_source.is_(False),
    )
    if not _subscription_active(selection.collection.source_key):
        # Nor can media that needs a subscription VODLoft is not signed in with.
        stmt = stmt.where(Episode.needs_subscription.is_(False))
    return stmt


def _types(selection: EpisodeSelection, stmt: Select) -> Select:
    """No episode types line: every type."""
    if not selection.ep_id_type_list:
        return stmt
    return stmt.where(episode_identifier_type_predicate(Episode.episode_identifier, set(selection.ep_id_type_list)))


def uses_seasons(selection: EpisodeSelection) -> bool:
    """Only a Collection identified by season filters its episodes by season."""
    return selection.collection.episode_identifier == EpisodeIdentifier.SEASONAL.value


def _seasons(s: Session, selection: EpisodeSelection, stmt: Select) -> Select:
    if not uses_seasons(selection):
        return stmt
    predicates = []
    if selection.season_ids:
        predicates.append(Episode.season_id.in_(selection.season_ids))
        if selection.include_upcoming_seasons:
            highest = s.scalar(select(func.max(Season.index)).where(Season.id.in_(selection.season_ids)))
            if highest is not None:
                predicates.append(Episode.season.has(Season.index > highest))
    if not predicates:
        return stmt.where(False)
    return stmt.where(or_(*predicates))


def _dates(selection: EpisodeSelection, stmt: Select) -> Select:
    published_at = _published_at()
    if selection.download_days_in_past > 0:
        cutoff = _utc_now() - timedelta(days=selection.download_days_in_past)
        # An episode with no publication instant is not left out by the days alone.
        stmt = stmt.where(or_(published_at.is_(None), published_at >= cutoff))

    if selection.download_starting_from is not None:
        local_start = datetime.combine(
            selection.download_starting_from,
            time.min,
            tzinfo=ZoneInfo(get_settings().timezone),
        )
        stmt = stmt.where(published_at.is_not(None), published_at >= local_start.astimezone(timezone.utc))

    if selection.download_episode_count > 0:
        newest = (
            stmt.with_only_columns(Episode.id)
            .order_by(published_at.desc(), Episode.id.desc())
            .limit(selection.download_episode_count)
        )
        stmt = select(Episode).where(Episode.id.in_(newest))
    return stmt


def _built_in_statement(s: Session, selection: EpisodeSelection, *, upto: str = "dates") -> Select:
    stmt = select(Episode).where(Episode.collection_id == selection.collection.id)
    stmt = _availability(selection, stmt)
    if upto == "availability":
        return stmt
    stmt = _types(selection, stmt)
    if upto == "types":
        return stmt
    stmt = _seasons(s, selection, stmt)
    if upto == "seasons":
        return stmt
    return _dates(selection, stmt)


def episodes_in_window(
        s: Session,
        selection: EpisodeSelection,
        *,
        only_episode_id: Optional[int] = None,
) -> list[Episode]:
    """Episodes that pass the built-in lines, newest first, before your own rules."""
    stmt = _built_in_statement(s, selection)
    if only_episode_id is not None:
        stmt = stmt.where(Episode.id == only_episode_id)
    return list(s.scalars(stmt.order_by(_published_at().desc(), Episode.id.desc())))


def wanted_episodes(
        s: Session,
        selection: EpisodeSelection,
        *,
        only_episode_id: Optional[int] = None,
) -> list[Episode]:
    """Episodes the profile downloads: the built-in lines, then your own rules."""
    episodes = episodes_in_window(s, selection, only_episode_id=only_episode_id)
    if not selection.rules:
        return episodes
    return [episode for episode in episodes if first_rule_leaving_out(selection.rules, episode) is None]


@dataclass
class WhichEpisodesResult:
    """How many indexed episodes each line leaves out, and why each episode is not downloaded."""

    total: int
    unavailable: int
    types: int
    seasons: int
    dates: int
    rules: list[int]
    downloaded: int
    # Episode id -> the line that left it out: unavailable, types, seasons, dates or rule:<index>.
    left_out_by: dict[int, str]


def which_episodes(s: Session, selection: EpisodeSelection) -> WhichEpisodesResult:
    def ids(stmt: Select) -> set[int]:
        return set(s.scalars(stmt.with_only_columns(Episode.id)))

    all_ids = ids(select(Episode).where(Episode.collection_id == selection.collection.id))
    available = ids(_built_in_statement(s, selection, upto="availability"))
    typed = ids(_built_in_statement(s, selection, upto="types"))
    seasoned = ids(_built_in_statement(s, selection, upto="seasons"))
    in_window = episodes_in_window(s, selection)

    left_out_by: dict[int, str] = {}
    for episode_id in all_ids - available:
        left_out_by[episode_id] = "unavailable"
    for episode_id in available - typed:
        left_out_by[episode_id] = "types"
    for episode_id in typed - seasoned:
        left_out_by[episode_id] = "seasons"
    window_ids = {episode.id for episode in in_window}
    for episode_id in seasoned - window_ids:
        left_out_by[episode_id] = "dates"

    rule_counts = [0] * len(selection.rules)
    for episode in in_window:
        index = first_rule_leaving_out(selection.rules, episode)
        if index is not None:
            rule_counts[index] += 1
            left_out_by[episode.id] = f"rule:{index}"

    return WhichEpisodesResult(
        total=len(all_ids),
        unavailable=len(all_ids - available),
        types=len(available - typed),
        seasons=len(typed - seasoned),
        dates=len(seasoned - window_ids),
        rules=rule_counts,
        downloaded=len(in_window) - sum(rule_counts),
        left_out_by=left_out_by,
    )
