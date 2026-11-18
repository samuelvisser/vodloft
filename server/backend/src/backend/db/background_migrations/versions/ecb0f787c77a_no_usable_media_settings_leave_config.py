"""Remove the "Monitor no-usable-media episodes" settings from config.yml.

Revision ID: ecb0f787c77a
Revises: 949968df4516

An episode without usable media is now one its Source no longer has, so its own
schedule and the minutes before it was deleted are gone.
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


revision = "ecb0f787c77a"
down_revision = "949968df4516"
title = "Remove the no-usable-media settings from the configuration"

_REMOVED = {
    "newEpisodeSchedule": {"monitorNoUsableMediaEpisodeCron", "monitorNoUsableMediaEpisodeCronEnabled"},
    "new_episode_schedule": {"monitor_no_usable_media_episode_cron", "monitor_no_usable_media_episode_cron_enabled"},
    "episodeStatusTiming": {"noUsableMediaDeleteAfterMinutes"},
    "episode_status_timing": {"no_usable_media_delete_after_minutes"},
}


def _without_settings(source: str) -> str:
    """Remove only the obsolete keys, leaving other text and comments as they are."""
    root = yaml.compose(source)
    if not isinstance(root, MappingNode):
        return source

    removed_lines: set[int] = set()
    for section_key, section_value in root.value:
        if (
            not isinstance(section_key, ScalarNode)
            or section_key.value not in _REMOVED
            or not isinstance(section_value, MappingNode)
        ):
            continue
        for key, value in section_value.value:
            if not isinstance(key, ScalarNode) or key.value not in _REMOVED[section_key.value]:
                continue
            # Each setting is written on one line.
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

    updated = _without_settings(original)
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
