"""The Which episodes filters of an imported Download Profile.

Importers describe a Download Profile the way the other program stored it: episode
types, seasons, one date limit and a list of rules. Applying a plan turns that into
VODLoft's ordered filters, in the order a new profile gets them: seasons, episode
types, the rules, then the date line.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Optional

from backend.types.download_profile_types import EpisodeFilterAction, EpisodeFilterField


@dataclass
class PlannedFilter:
    action: str
    field: str
    pattern: Optional[str] = None
    duration_operator: Optional[str] = None
    duration_seconds: Optional[int] = None
    episode_types: Optional[list[str]] = None
    season_slugs: Optional[list[str]] = None
    include_upcoming: bool = False
    days: Optional[int] = None
    count: Optional[int] = None
    starting_from: Optional[date] = None


def _day(value: object) -> Optional[date]:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _date_line(values: Mapping[str, object]) -> Optional[PlannedFilter]:
    count = int(values.get("download_episode_count") or 0)
    days = int(values.get("download_days_in_past") or 0)
    starting_from = _day(values.get("download_starting_from"))
    only = EpisodeFilterAction.ONLY.value
    if count > 0:
        return PlannedFilter(only, EpisodeFilterField.PUBLISHED.value, count=count)
    if days > 0:
        downloaded = values.get("retention_from") == "downloaded"
        field = EpisodeFilterField.DOWNLOADED if downloaded else EpisodeFilterField.PUBLISHED
        return PlannedFilter(only, field.value, days=days)
    if starting_from is not None:
        return PlannedFilter(only, EpisodeFilterField.PUBLISHED.value, starting_from=starting_from)
    return None


def filters_from_plan(values: Mapping[str, object], *, seasons: bool) -> list[PlannedFilter]:
    """The filters of a planned Download Profile. With ``seasons``, it starts with a seasons line.

    The seasons line starts with the slugs the plan lists; an importer that links seasons
    one by one adds them later.
    """
    filters: list[PlannedFilter] = []
    if seasons:
        slugs = [str(season.get("slug") if isinstance(season, Mapping) else season)
                 for season in values.get("seasons") or []]
        filters.append(PlannedFilter(
            EpisodeFilterAction.ONLY.value, EpisodeFilterField.SEASONS.value,
            season_slugs=slugs, include_upcoming=bool(values.get("include_upcoming_seasons")),
        ))
    types = list(values.get("ep_id_type_list") or [])
    if types:
        filters.append(PlannedFilter(EpisodeFilterAction.ONLY.value, EpisodeFilterField.TYPES.value, episode_types=types))
    for rule in values.get("rules") or []:
        pattern = rule.get("pattern")
        if pattern is not None and rule.get("ignore_case") and not str(pattern).startswith("(?i)"):
            pattern = f"(?i){pattern}"
        filters.append(PlannedFilter(
            str(rule["action"]), str(rule["field"]), pattern=pattern,
            duration_operator=rule.get("duration_operator"), duration_seconds=rule.get("duration_seconds"),
            episode_types=rule.get("episode_types"),
        ))
    date_line = _date_line(values)
    if date_line is not None:
        filters.append(date_line)
    return filters
