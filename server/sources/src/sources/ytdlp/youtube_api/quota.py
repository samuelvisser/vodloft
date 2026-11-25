"""Counting the units the API key spends, per Pacific-time day.

Google does not tell an API key its limit or what is left, so VODLoft counts
its own units and plans with the split from Settings › Sources. Google resets
the quota at midnight Pacific time.

A summary of each day is logged at info level once the next one starts.
With debug logging on, every call and every call a full share refused is
logged too. The usage
log in Settings keeps the same lines in a file that survives restarts.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from config import get_settings

from ... import ytdlp_runner as runner
from ...contract import QuickCheckCost

PACIFIC = ZoneInfo("America/Los_Angeles")
SEARCH_UNITS = 102
"""One search: the search call itself and one batch each of channel and video details."""
USAGE_LOG_NAME = "youtube-api-usage.log"
_lock = threading.Lock()
logger = logging.getLogger(__name__)
_usage_log_lines: dict[Path, int] = {}
"""Lines in each usage log, counted once, so trimming it needs no read per line."""


class Share(StrEnum):
    """What a call is for, which decides the part of the daily quota it spends."""

    CHECKS = "checks"
    """Quick checks for new videos and full re-scans."""
    SEARCH = "search"
    RESERVE = "reserve"
    """Adding collections, testing the key and manual refreshes: whatever the other two leave."""


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


def _fresh_day(now: datetime | None) -> dict:
    return {"day": pacific_day(now).isoformat(), "used": {}, "calls": {}, "refused": {}, "exhausted": False}


def _read(now: datetime | None) -> dict:
    """Today's counts. A state from an earlier Pacific day is a fresh day, once that day's summary is recorded."""
    try:
        state = json.loads(_state_path().read_text())
    except (OSError, ValueError):
        state = {}
    today = pacific_day(now).isoformat()
    if isinstance(state, dict) and state.get("day") == today:
        return state
    fresh = _fresh_day(now)
    if isinstance(state, dict) and isinstance(state.get("day"), str) and state["day"] < today:
        _record(_summary(state), now, level=logging.INFO)
        _write(fresh)
    return fresh

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


def try_spend(share: Share, units: int, *, call: str, now: datetime | None = None, force: bool = False) -> bool:
    """Count units for a call about to be made, when its share has room for them.

    ``call`` is the API endpoint, for the usage log. ``force`` counts the
    units even when the share is full, for the one call Test key makes.
    Nothing is spent once Google said the quota is used up.
    """
    with _lock:
        state = _read(now)
        limit = _limits()[share]
        used = state.setdefault("used", {})
        spent = int(used.get(share.value, 0))
        if state.get("exhausted") or (not force and spent + units > limit):
            refused = state.setdefault("refused", {})
            refused[share.value] = int(refused.get(share.value, 0)) + 1
            _write(state)
            reason = "Google said today's quota is used up" if state.get("exhausted") else f"the {share.value} share is full"
            _record([f"Refused {call} ({_units(units)}): {reason}, {spent:,} of {limit:,} used"], now)
            return False
        used[share.value] = spent + units
        calls = state.setdefault("calls", {}).setdefault(share.value, {})
        count, total = calls.get(call, (0, 0))
        calls[call] = [count + 1, total + units]
        _write(state)
        _record([f"{share.value}: {call} ({_units(units)}), {spent + units:,} of {limit:,} used"], now)
        return True


def mark_exhausted(now: datetime | None = None) -> None:
    """Google answered that the quota is used up: treat the rest of the day as used."""
    with _lock:
        state = _read(now)
        state["exhausted"] = True
        _write(state)
        counted = sum(int(units) for units in (state.get("used") or {}).values())
        _record([f"Google says today's quota is used up, after VODLoft counted {counted:,} units"], now)


def _units(units: int) -> str:
    return "1 unit" if units == 1 else f"{units:,} units"


def _summary(state: dict) -> list[str]:
    """What one day spent, per share and per endpoint, and how many calls a full share refused."""
    limits = _limits()
    used = state.get("used") or {}
    calls = state.get("calls") or {}
    refused = state.get("refused") or {}
    total = sum(int(units) for units in used.values())
    lines = [f"Summary of {state['day']} (Pacific time): {total:,} of {get_settings().youtube_api.daily_quota:,} units used"
             + (", and Google said the quota was used up" if state.get("exhausted") else "")]
    for share in Share:
        endpoints = ", ".join(
            f"{endpoint} {_units(units)} in {count:,} {'call' if count == 1 else 'calls'}"
            for endpoint, (count, units) in sorted(calls.get(share.value, {}).items(), key=lambda item: -item[1][1])
        )
        line = f"  {share.value}: {int(used.get(share.value, 0)):,} of {limits[share]:,} units"
        if endpoints:
            line += f" ({endpoints})"
        if refusals := int(refused.get(share.value, 0)):
            line += f", {refusals:,} {'call' if refusals == 1 else 'calls'} refused"
        lines.append(line)
    return lines


def usage_log_path() -> Path:
    return runner.ytdlp_directory() / USAGE_LOG_NAME


def _record(lines: list[str], now: datetime | None, *, level: int = logging.DEBUG) -> None:
    """Log usage, and add it to the usage log when that is on. Runs under ``_lock``."""
    logger.log(level, "YouTube API usage: %s", "\n".join(lines))
    settings = get_settings()
    if not settings.youtube_api.usage_log_enabled:
        return
    stamp = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(settings.timezone)).isoformat(timespec="seconds")
    try:
        _append(usage_log_path(), [f"{stamp} {line}" for line in lines], settings.youtube_api.usage_log_max_lines)
    except OSError as exc:
        logger.warning("Could not write the YouTube API usage log: %s", exc)


def _append(path: Path, lines: list[str], max_lines: int) -> None:
    """Add lines to a log, and once it grows a tenth past ``max_lines``, keep only the newest ``max_lines``."""
    if path not in _usage_log_lines:
        try:
            with path.open("rb") as existing:
                _usage_log_lines[path] = sum(1 for _ in existing)
        except FileNotFoundError:
            _usage_log_lines[path] = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log:
        log.writelines(f"{line}\n" for line in lines)
    _usage_log_lines[path] += len(lines)
    if _usage_log_lines[path] > max_lines + max(max_lines // 10, 1):
        kept = path.read_text(encoding="utf-8").splitlines(keepends=True)[-max_lines:]
        temporary = path.with_suffix(".tmp")
        temporary.write_text("".join(kept), encoding="utf-8")
        temporary.replace(path)
        _usage_log_lines[path] = len(kept)


def rescan_units(episode_counts: list[int]) -> int:
    """Units one full re-scan of these collections costs: a page of IDs and a batch of details per 50 videos."""
    return sum(2 * max(math.ceil(count / 50), 1) for count in episode_counts)


MIN_CHECK_MINUTES = 10
"""No collection is quick-checked more often than this, however much quota is left."""
_LONGEST_CHECK_MINUTES = 24 * 60
_DETAILS_MARGIN = 1.1
"""A check costs a batch of details on top when something is new; a tenth more covers those."""


def daily_check_units(costs: Iterable[QuickCheckCost], minutes: int) -> float:
    """The units a day of quick checks costs when each collection is checked every ``minutes``, or less often
    when it waits longer anyway."""
    return sum(cost.units * 24 * 60 / max(minutes, cost.least_minutes) for cost in costs) * _DETAILS_MARGIN


def check_interval_minutes(costs: Sequence[QuickCheckCost], rescan_cost: int, checks_quota: int) -> int | None:
    """The shortest time between two quick checks of a collection that keeps a day of checks, together with the
    daily re-scan, inside the checks share. Never less than ``MIN_CHECK_MINUTES``. None when the share does not
    leave room for a check of every collection a day."""
    room = checks_quota - rescan_cost
    if room <= 0 or daily_check_units(costs, _LONGEST_CHECK_MINUTES) > room:
        return None
    low, high = MIN_CHECK_MINUTES, _LONGEST_CHECK_MINUTES
    while low < high:
        middle = (low + high) // 2
        if daily_check_units(costs, middle) <= room:
            high = middle
        else:
            low = middle + 1
    return low
