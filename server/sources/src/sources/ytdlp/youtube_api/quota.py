"""Counting the units the API key spends, per Pacific-time day.

Google does not tell an API key its limit or what is left, so VODLoft counts
its own units and plans with the split from Settings › Sources. Google resets
the quota at midnight Pacific time.
"""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo

from config import get_settings

from ... import ytdlp_runner as runner

PACIFIC = ZoneInfo("America/Los_Angeles")
SEARCH_UNITS = 102
"""One search: the search call itself and one batch each of channel and video details."""
_lock = threading.Lock()


class Share(StrEnum):
    """What a call is for, which decides the part of the daily quota it spends."""

    CHECKS = "checks"
    """Quick checks for new videos and full re-scans."""
    SEARCH = "search"
    RESERVE = "reserve"
    """Adding shows, testing the key and manual refreshes: whatever the other two leave."""


@dataclass(frozen=True)
class ShareUsage:
    share: Share
    used: int
    limit: int


@dataclass(frozen=True)
class QuotaStatus:
    day: date
    shares: tuple[ShareUsage, ...]
    daily_quota: int
    exhausted: bool
    """Google said the quota was used up before VODLoft's own count reached it."""
    resets_at: datetime

    @property
    def used(self) -> int:
        return sum(usage.used for usage in self.shares)

    def usage(self, share: Share) -> ShareUsage:
        return next(usage for usage in self.shares if usage.share == share)


def _state_path() -> Path:
    return runner.ytdlp_directory() / "youtube-api-quota.json"


def pacific_day(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(PACIFIC).date()


def next_reset(now: datetime | None = None) -> datetime:
    day = pacific_day(now) + timedelta(days=1)
    return datetime.combine(day, time(), tzinfo=PACIFIC).astimezone(timezone.utc)


def _limits() -> dict[Share, int]:
    settings = get_settings().youtube_api
    return {
        Share.CHECKS: settings.checks_quota,
        Share.SEARCH: settings.search_quota,
        Share.RESERVE: max(settings.daily_quota - settings.checks_quota - settings.search_quota, 0),
    }


def _read(now: datetime | None) -> dict:
    """Today's counts. A state from an earlier Pacific day is a fresh day."""
    try:
        state = json.loads(_state_path().read_text())
    except (OSError, ValueError):
        state = {}
    if not isinstance(state, dict) or state.get("day") != pacific_day(now).isoformat():
        return {"day": pacific_day(now).isoformat(), "used": {}, "exhausted": False}
    return state


def _write(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.replace(path)


def status(now: datetime | None = None) -> QuotaStatus:
    with _lock:
        state = _read(now)
    limits = _limits()
    used = state.get("used") or {}
    return QuotaStatus(
        day=date.fromisoformat(state["day"]),
        shares=tuple(ShareUsage(share, int(used.get(share.value, 0)), limits[share]) for share in Share),
        daily_quota=get_settings().youtube_api.daily_quota,
        exhausted=bool(state.get("exhausted")),
        resets_at=next_reset(now),
    )


def try_spend(share: Share, units: int, *, now: datetime | None = None, force: bool = False) -> bool:
    """Count units for a call about to be made, when its share has room for them.

    ``force`` counts them even when the share is full, for the one call Test
    key makes. Nothing is spent once Google said the quota is used up.
    """
    with _lock:
        state = _read(now)
        if state.get("exhausted"):
            return False
        used = state.setdefault("used", {})
        spent = int(used.get(share.value, 0))
        if not force and spent + units > _limits()[share]:
            return False
        used[share.value] = spent + units
        _write(state)
        return True


def mark_exhausted(now: datetime | None = None) -> None:
    """Google answered that the quota is used up: treat the rest of the day as used."""
    with _lock:
        state = _read(now)
        state["exhausted"] = True
        _write(state)


def rescan_units(episode_counts: list[int]) -> int:
    """Units one full re-scan of these shows costs: a page of IDs and a batch of details per 50 videos."""
    return sum(2 * max(math.ceil(count / 50), 1) for count in episode_counts)


def check_interval_minutes(show_count: int, rescan_cost: int, checks_quota: int, min_interval: int) -> int | None:
    """How often each show can get a quick check from what the daily re-scan leaves of the checks share.

    A check costs one unit, plus a batch of details when something is new;
    the tenth on top covers those. None when the share leaves no room for checks.
    """
    if show_count == 0:
        return min_interval
    room = checks_quota - rescan_cost
    if room <= 0:
        return None
    checks_per_show = room / (show_count * 1.1)
    return max(min_interval, math.ceil(24 * 60 / checks_per_show))
