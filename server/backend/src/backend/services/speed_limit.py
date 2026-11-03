"""The download speed limit from Settings › Downloads, as the downloader enforces it.

"Leave room for streaming" keeps downloads to about half of the connection. VODLoft estimates the connection from
the fastest recent downloads that nothing slowed down; until it has measured a few, downloads run at full speed.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from config import get_settings
from config.settings.base import get_config_path
from config.settings.submodels import SpeedLimitMode
from downloader.speed import SpeedPolicy, limiter

logger = logging.getLogger(__name__)

_MB = 1_000_000
STREAMING_SHARE = 0.5


def _samples_path() -> Path:
    return get_config_path().parent / "speed-samples.json"


_SAMPLES_KEPT = 20
_samples: list[float] = []


def _load_samples() -> list[float]:
    try:
        values = json.loads(_samples_path().read_text())
    except (OSError, ValueError):
        values = []
    _samples[:] = [float(value) for value in values if isinstance(value, (int, float)) and value > 0][-_SAMPLES_KEPT:]
    return list(_samples)


def _store_sample(sample: float) -> None:
    _samples[:] = [*_samples, sample][-_SAMPLES_KEPT:]
    try:
        path = _samples_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_samples))
    except OSError:
        logger.debug("Could not store the download speed measurements", exc_info=True)


def _minutes(text: str) -> int:
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def paused_until(now: datetime | None = None) -> datetime | None:
    """When the night pause ends, if downloads are paused right now."""
    settings = get_settings()
    download = settings.download_settings
    if not download.pause_at_night or download.pause_start == download.pause_end:
        return None
    zone = ZoneInfo(settings.timezone)
    now = (now or datetime.now(zone)).astimezone(zone)
    minute = now.hour * 60 + now.minute
    start, end = _minutes(download.pause_start), _minutes(download.pause_end)
    inside = start <= minute < end if start < end else (minute >= start or minute < end)
    if not inside:
        return None
    ends = now.replace(hour=end // 60, minute=end % 60, second=0, microsecond=0)
    return ends if ends > now else ends + timedelta(days=1)


@dataclass(frozen=True)
class SpeedStatus:
    limit_mbps: float | None
    """None is full speed."""
    estimate_mbps: float | None
    """The connection as VODLoft measured it, or None until it has a few measurements."""
    paused_until: datetime | None


def status(now: datetime | None = None) -> SpeedStatus:
    download = get_settings().download_settings
    fastest = limiter.fastest_recent()
    estimate = fastest / _MB if fastest else None
    if download.speed_limit_mode == SpeedLimitMode.CUSTOM:
        limit = download.speed_limit_mbps
    elif download.speed_limit_mode == SpeedLimitMode.STREAMING and estimate:
        limit = round(estimate * STREAMING_SHARE, 2)
    else:
        limit = None
    return SpeedStatus(limit, estimate, paused_until(now))


def _policy() -> SpeedPolicy:
    current = status()
    return SpeedPolicy(
        bytes_per_second=current.limit_mbps * _MB if current.limit_mbps else None,
        paused_until=current.paused_until.timestamp() if current.paused_until else None,
    )


class _Cached:
    """The policy is asked for every chunk; settings only need reading once a second."""

    def __init__(self) -> None:
        self._value = SpeedPolicy()
        self._at = 0.0

    def __call__(self) -> SpeedPolicy:
        now = time.monotonic()
        if now - self._at >= 1.0:
            self._value, self._at = _policy(), now
        return self._value


def start_speed_limit() -> None:
    """Hand the downloader the speed limit; call once when VODLoft starts."""
    limiter.configure(_Cached(), samples=_load_samples(), on_sample=_store_sample)
