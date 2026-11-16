"""Rename the RSS cache to the Stream Video Cache, in config.yml and on disk.

Revision ID: a158febaa920
Revises: 875ce72375ca

IPTV and WebDAV stream profiles use the cache too, so ``rssCacheRoot`` becomes ``streamCacheRoot``,
``rssCacheRetentionSeconds`` becomes ``streamCacheRetentionSeconds`` and its default folder
``.vodloft-rss-cache`` becomes ``.vodloft-stream-cache``. A configured folder of that old name gets
the new name, and the cache moves to it, so the video VODLoft already joined stays. Changing the
config file and the download folder is why this is not part of the database migration.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import stat
import tempfile
from pathlib import Path

import yaml
from yaml.nodes import MappingNode, ScalarNode

from config import get_settings
from config.registry import reload_settings
from config.settings.base import get_config_path


revision = "a158febaa920"
down_revision = "875ce72375ca"
title = "Rename the RSS cache to the Stream Video Cache"

logger = logging.getLogger(__name__)

_SECTIONS = {"downloadSettings", "download_settings"}
_RENAMED = {
    "rssCacheRoot": "streamCacheRoot",
    "rss_cache_root": "stream_cache_root",
    "rssCacheRetentionSeconds": "streamCacheRetentionSeconds",
    "rss_cache_retention_seconds": "stream_cache_retention_seconds",
}
_ROOT_KEYS = {"rssCacheRoot", "rss_cache_root"}
_OLD_FOLDER = ".vodloft-rss-cache"
_NEW_FOLDER = ".vodloft-stream-cache"


def _renamed_settings(source: str) -> str:
    """Rename the cache's keys, and the old default folder name in its folder, leaving the rest of the file as it is.

    A key whose new name is already there is left for the user, as VODLoft reads the new one.
    """
    root = yaml.compose(source) if source.strip() else None
    if not isinstance(root, MappingNode):
        return source
    edits: list[tuple[int, int, str]] = []
    for section_key, section in root.value:
        if (
            not isinstance(section_key, ScalarNode)
            or section_key.value not in _SECTIONS
            or not isinstance(section, MappingNode)
        ):
            continue
        present = {key.value for key, _ in section.value if isinstance(key, ScalarNode)}
        for key, value in section.value:
            if not isinstance(key, ScalarNode) or key.value not in _RENAMED or _RENAMED[key.value] in present:
                continue
            raw_key = source[key.start_mark.index:key.end_mark.index]
            edits.append((key.start_mark.index, key.end_mark.index, raw_key.replace(key.value, _RENAMED[key.value])))
            if key.value in _ROOT_KEYS and isinstance(value, ScalarNode) and Path(value.value).name == _OLD_FOLDER:
                raw_value = source[value.start_mark.index:value.end_mark.index]
                edits.append((value.start_mark.index, value.end_mark.index, raw_value.replace(_OLD_FOLDER, _NEW_FOLDER)))
    for begin, end, text in sorted(edits, reverse=True):
        source = source[:begin] + text + source[end:]
    return source


def _rewrite_config() -> None:
    path = get_config_path()
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    updated = _renamed_settings(original)
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
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    reload_settings()


def _merge(source: Path, target: Path) -> None:
    """Move what ``source`` holds into ``target``; a file ``target`` already has stays as it is."""
    target.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        destination = target / entry.name
        if entry.is_dir() and not entry.is_symlink() and destination.is_dir():
            _merge(entry, destination)
        elif not destination.exists() and not destination.is_symlink():
            shutil.move(entry, destination)


def _move_cache_folder() -> None:
    """Move the cache from its old default folder into the folder of the new name next to it."""
    root = Path(get_settings().download_settings.stream_cache_root)
    old = root.with_name(_OLD_FOLDER)
    if root.name != _NEW_FOLDER or old.is_symlink() or not old.is_dir():
        return
    if not root.exists():
        old.rename(root)
    else:
        # Streaming may have cached a video in the new folder before this migration ran.
        _merge(old, root)
        shutil.rmtree(old, ignore_errors=True)
    logger.info("Moved the Stream Video Cache from %s to %s", old, root)


async def migrate(context) -> None:
    context.raise_if_canceled()
    await asyncio.to_thread(_rewrite_config)
    context.raise_if_canceled()
    await asyncio.to_thread(_move_cache_folder)
