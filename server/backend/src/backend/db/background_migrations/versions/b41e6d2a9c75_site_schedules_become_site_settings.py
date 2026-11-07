"""Move each Site's own scheduling in config.yml from ``siteSchedules`` to ``siteSettings``.

Revision ID: b41e6d2a9c75
Revises: 7f51410a2578

A Site's own settings now cover its Download Profile defaults too, so they live under
``siteSettings``. The three lookup times of upcoming and live episodes are one setting
there, ``lookupMinutes``. Changing the config file is why this is not part of the
database migration.
"""

from __future__ import annotations

from pathlib import Path
import os
import stat
import tempfile

import yaml
from yaml.nodes import MappingNode, ScalarNode

from config.registry import reload_settings
from config.settings.base import get_config_path


revision = "b41e6d2a9c75"
down_revision = "7f51410a2578"
title = "Move each Site's scheduling to its settings in the configuration"

_OLD = {"siteSchedules", "site_schedules"}
_NEW = "siteSettings"
_RENAMED = {
    "metadataRefresh": "metadataRefresh", "metadata_refresh": "metadataRefresh",
    "upcomingAndLive": "upcomingAndLive", "upcoming_and_live": "upcomingAndLive",
}
_MINUTES = {
    "pendingUpcomingMinutes": "upcoming", "pending_upcoming_minutes": "upcoming",
    "pendingStartingMinutes": "starting", "pending_starting_minutes": "starting",
    "pendingLiveMinutes": "live", "pending_live_minutes": "live",
}


def _site_settings(schedule: dict) -> dict:
    """One Site's settings from its schedule; a setting it left out stays out."""
    settings = {_RENAMED[key]: value for key, value in schedule.items() if key in _RENAMED and value is not None}
    if settings.get("metadataRefresh") is False:
        # YAML reads an unquoted off as false.
        settings["metadataRefresh"] = "off"
    minutes = {_MINUTES[key]: value for key, value in schedule.items() if key in _MINUTES and value is not None}
    if len(minutes) == 3:
        settings["lookupMinutes"] = {name: minutes[name] for name in ("upcoming", "starting", "live")}
    return settings


def _block_lines(key: ScalarNode, value, lines: list[str]) -> range:
    """The lines a top-level key and its value take up. Comments and blank lines after the value belong
    to what follows, so they stay."""
    end = value.end_mark.line + (1 if value.end_mark.column else 0)
    while end - 1 > key.start_mark.line and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    return range(key.start_mark.line, end)


def _with_site_settings(source: str) -> str:
    """Replace the ``siteSchedules`` block with a ``siteSettings`` block, leaving the rest of the file as it is."""
    root = yaml.compose(source) if source.strip() else None
    if not isinstance(root, MappingNode):
        return source
    lines = source.splitlines(keepends=True)
    blocks = {
        key.value: _block_lines(key, value, lines) for key, value in root.value
        if isinstance(key, ScalarNode) and key.value in _OLD | {_NEW}
    }
    old = next((blocks[name] for name in _OLD if name in blocks), None)
    if old is None:
        return source
    document = yaml.safe_load(source)
    schedules = next((document[name] for name in _OLD if name in document), None) or {}
    settings = {
        str(site_key): converted
        for site_key, schedule in schedules.items()
        if isinstance(schedule, dict) and (converted := _site_settings(schedule))
    }
    # A Site's settings that are already there win.
    for site_key, own in (document.get(_NEW) or {}).items():
        settings[str(site_key)] = {**settings.get(str(site_key), {}), **(own or {})}

    block = yaml.safe_dump({_NEW: settings}, default_flow_style=False, sort_keys=False) if settings else ""
    removed = set().union(*blocks.values())
    return "".join(
        (block if number == old.start else "") + ("" if number in removed else line)
        for number, line in enumerate(lines)
    )


async def migrate(context) -> None:
    context.raise_if_canceled()
    path = get_config_path()
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return

    updated = _with_site_settings(original)
    if updated == original:
        return

    # Write into the same directory so replacement is atomic, and keep the
    # original file mode rather than exposing configuration secrets.
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".vodloft-settings-",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(updated)

        temporary_path.chmod(stat.S_IMODE(path.stat().st_mode))
        context.raise_if_canceled()
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    reload_settings()
