"""Rename the show asset settings in config.yml to their Collection names.

Shows became Collections in VODLoft 0.6.0. The two download settings that
named shows are renamed in place, keeping every other line and comment.

Revision ID: c0f6328c88f7
Revises: 5e2b8c71d0a4
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


revision = "c0f6328c88f7"
down_revision = "5e2b8c71d0a4"
title = "Rename Collection asset settings"

_RENAMES = {
    "downloadShowAssets": "downloadCollectionAssets",
    "download_show_assets": "download_collection_assets",
    "showArtworkFallbackFormat": "collectionArtworkFallbackFormat",
    "show_artwork_fallback_format": "collection_artwork_fallback_format",
}


def _renamed_settings(source: str) -> str:
    """Rename only the targeted YAML keys, preserving other text and comments."""
    root = yaml.compose(source)
    if not isinstance(root, MappingNode):
        return source

    edits: list[tuple[int, int, str]] = []
    removed_lines: set[int] = set()
    for section_key, section_value in root.value:
        if (
            not isinstance(section_key, ScalarNode)
            or section_key.value not in {"downloadSettings", "download_settings"}
            or not isinstance(section_value, MappingNode)
        ):
            continue
        present = {key.value for key, _ in section_value.value if isinstance(key, ScalarNode)}
        for key, value in section_value.value:
            if not isinstance(key, ScalarNode) or key.value not in _RENAMES:
                continue
            new_name = _RENAMES[key.value]
            if new_name in present or _RENAMES.get(new_name) in present:
                # The new key is already there: keep its value and drop the
                # obsolete single-line scalar setting.
                if isinstance(value, ScalarNode) and value.end_mark.line == key.start_mark.line:
                    removed_lines.add(key.start_mark.line)
                continue
            begin, end = key.start_mark.index, key.end_mark.index
            edits.append((begin, end, source[begin:end].replace(key.value, new_name)))

    for begin, end, text in sorted(edits, reverse=True):
        source = source[:begin] + text + source[end:]
    if removed_lines:
        lines = source.splitlines(keepends=True)
        source = "".join(line for number, line in enumerate(lines) if number not in removed_lines)
    return source


async def migrate(context) -> None:
    context.raise_if_canceled()
    path = get_config_path()
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return

    updated = _renamed_settings(original)
    if updated == original:
        return

    # Write into the same directory so replacement is atomic, and preserve
    # the original file mode rather than exposing configuration secrets.
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

    # The settings instance was loaded before background migrations started.
    # Install the corrected configuration immediately for active workers/UI.
    reload_settings()
