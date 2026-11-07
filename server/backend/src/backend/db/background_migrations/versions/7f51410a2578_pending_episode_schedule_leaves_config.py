"""Remove the "Monitor pending episodes" schedule from config.yml.

Revision ID: 7f51410a2578
Revises: e8ea12937f41

Upcoming and live episodes of every Source now follow one rhythm, which each Site
sets, so the schedule that only The Daily Wire's episodes followed is gone.
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


revision = "7f51410a2578"
down_revision = "e8ea12937f41"
title = "Remove the pending episode monitor schedule from the configuration"

_SECTIONS = {"newEpisodeSchedule", "new_episode_schedule"}
_REMOVED = {
    "monitorPendingEpisodeCron",
    "monitor_pending_episode_cron",
    "monitorPendingEpisodeCronEnabled",
    "monitor_pending_episode_cron_enabled",
}


def _without_monitor_schedule(source: str) -> str:
    """Remove only the obsolete keys, leaving other text and comments as they are."""
    root = yaml.compose(source)
    if not isinstance(root, MappingNode):
        return source

    removed_lines: set[int] = set()
    for section_key, section_value in root.value:
        if (
            not isinstance(section_key, ScalarNode)
            or section_key.value not in _SECTIONS
            or not isinstance(section_value, MappingNode)
        ):
            continue
        for key, value in section_value.value:
            if not isinstance(key, ScalarNode) or key.value not in _REMOVED:
                continue
            # Both settings are written on one line each.
            if isinstance(value, ScalarNode) and value.end_mark.line == key.start_mark.line:
                removed_lines.add(key.start_mark.line)

    if not removed_lines:
        return source
    lines = source.splitlines(keepends=True)
    return "".join(line for number, line in enumerate(lines) if number not in removed_lines)


async def migrate(context) -> None:
    context.raise_if_canceled()
    path = get_config_path()
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return

    updated = _without_monitor_schedule(original)
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
