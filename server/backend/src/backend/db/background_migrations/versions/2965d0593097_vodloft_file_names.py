"""Rename the files and keyring entries that VODLoft kept under WireLoft names.

The download folders hold hidden ``.wireloft-*`` files and folders: lock
folders, the RSS cache, local HLS bundle markers, and what an unclean shutdown
left of a download in progress. The leftovers also start with a WireLoft
marker. They are renamed and their markers rewritten, and then the startup
recovery runs again so it finishes those downloads under their new names.

The Daily Wire login moves to the VODLoft keyring service, the default
temporary download folder and secret key file get their VODLoft names, and
config.yml follows when it names the old secret key file.

Revision ID: 2965d0593097
Revises: b7d2f49c0a13
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
import tempfile
from pathlib import Path

import keyring
import yaml
from keyring.errors import KeyringError
from yaml.nodes import MappingNode, ScalarNode

from config import get_settings
from config.registry import reload_settings
from config.settings.base import get_config_path


revision = "2965d0593097"
down_revision = "b7d2f49c0a13"
title = "Rename WireLoft files to VODLoft"

logger = logging.getLogger(__name__)

_OLD_NAME_PART = ".wireloft-"
_NEW_NAME_PART = ".vodloft-"
# (old, new) leading bytes of the marker files a download in progress keeps.
_MARKER_MAGIC = (
    (b"WIRELOFT_DOWNLOAD_PATH_RESERVATION_V1\0", b"VODLOFT_DOWNLOAD_PATH_RESERVATION_V1\0"),
    (b"WIRELOFT_PUBLICATION_LOCK_V1\0", b"VODLOFT_PUBLICATION_LOCK_V1\0"),
    (b"WIRELOFT_STAGED_DOWNLOAD_PUBLICATION_V1\0", b"VODLOFT_STAGED_DOWNLOAD_PUBLICATION_V1\0"),
    (b"WIRELOFT_STAGED_DOWNLOAD_PUBLICATION_V2\0", b"VODLOFT_STAGED_DOWNLOAD_PUBLICATION_V2\0"),
)
_AUXILIARY_JOURNAL = ".vodloft-auxiliary-publication"
_AUXILIARY_JOURNAL_FORMAT = ("wireloft-auxiliary-publication-v1", "vodloft-auxiliary-publication-v1")
_MAX_MARKER_BYTES = 64 * 1024
_TEMPORARY_ROOT_NAMES = ("wireloft-downloads", "vodloft-downloads")
_SECRET_FILE_NAMES = ("wl_secret.key", "vodloft_secret.key")
_KEYRING_SERVICES = ("wireloft-dailywire-auth", "vodloft-dailywire-auth")
_RECOVERY_POLL_SECONDS = 1.0


def _rename(source: Path, target: Path) -> bool:
    """Rename without replacing anything already at the target."""
    if target.exists() or target.is_symlink():
        logger.warning("Not renaming %s, because %s already exists", source, target)
        return False
    os.rename(source, target)
    return True


def _replace_contents(path: Path, contents: bytes) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".vodloft-rename-", delete=False) as temporary:
        temporary.write(contents)
        temporary.flush()
        os.fsync(temporary.fileno())
    temporary_path = Path(temporary.name)
    try:
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _rewrite_marker(path: Path) -> None:
    """Give a marker file left by a download in progress its VODLoft marker."""
    try:
        if path.stat().st_size > _MAX_MARKER_BYTES:
            return
        contents = path.read_bytes()
    except OSError:
        return
    if path.name == _AUXILIARY_JOURNAL:
        try:
            record = json.loads(contents)
        except ValueError:
            return
        if isinstance(record, dict) and record.get("format") == _AUXILIARY_JOURNAL_FORMAT[0]:
            record["format"] = _AUXILIARY_JOURNAL_FORMAT[1]
            _replace_contents(path, json.dumps(record).encode())
        return
    for old, new in _MARKER_MAGIC:
        if contents.startswith(old):
            _replace_contents(path, new + contents[len(old):])
            return


def _rename_tree(root: Path, *, configured: set[Path]) -> int:
    """Rename every WireLoft-named file and folder below ``root``. Returns how many were renamed.

    A folder that the settings name explicitly keeps its name, because VODLoft
    would create it again under the old name.
    """
    renamed = 0
    for directory, folders, files in os.walk(root):
        parent = Path(directory)
        for index, name in enumerate(folders):
            if _OLD_NAME_PART in name and parent / name not in configured:
                new_name = name.replace(_OLD_NAME_PART, _NEW_NAME_PART, 1)
                if _rename(parent / name, parent / new_name):
                    folders[index] = new_name
                    renamed += 1
        for name in files:
            path = parent / name
            if _OLD_NAME_PART in name:
                new_path = parent / name.replace(_OLD_NAME_PART, _NEW_NAME_PART, 1)
                if not _rename(path, new_path):
                    continue
                path = new_path
                renamed += 1
            if path.name.startswith(_NEW_NAME_PART):
                _rewrite_marker(path)
    return renamed


def _rename_default_temporary_root() -> None:
    """Move the old default temporary download folder when VODLoft uses the new default."""
    temporary_root = Path(get_settings().download_settings.temporary_download_root)
    old_name, new_name = _TEMPORARY_ROOT_NAMES
    if temporary_root != Path(tempfile.gettempdir()) / new_name:
        return
    old_root = temporary_root.with_name(old_name)
    if old_root.is_dir():
        _rename(old_root, temporary_root)


def _renamed_secret_file_setting(source: str) -> tuple[str, Path] | None:
    """config.yml with the VODLoft secret key file name, and the old file, when it names the old one."""
    root = yaml.compose(source)
    if not isinstance(root, MappingNode):
        return None
    for section_key, section in root.value:
        if (
            not isinstance(section_key, ScalarNode)
            or section_key.value != "crypto"
            or not isinstance(section, MappingNode)
        ):
            continue
        for key, value in section.value:
            if (
                isinstance(key, ScalarNode)
                and key.value in {"defaultSecretFile", "default_secret_file"}
                and isinstance(value, ScalarNode)
                and Path(value.value).name == _SECRET_FILE_NAMES[0]
            ):
                begin, end = value.start_mark.index, value.end_mark.index
                raw = source[begin:end].replace(_SECRET_FILE_NAMES[0], _SECRET_FILE_NAMES[1])
                return source[:begin] + raw + source[end:], Path(value.value)
    return None


def _rename_secret_file() -> None:
    path = get_config_path()
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        original = None
    renamed = _renamed_secret_file_setting(original) if original is not None else None
    if renamed is not None:
        updated, old_secret = renamed
        if old_secret.is_file():
            _rename(old_secret, old_secret.with_name(_SECRET_FILE_NAMES[1]))
        _replace_contents(path, updated.encode("utf-8"))
        reload_settings()
        return

    secret = Path(get_settings().crypto.default_secret_file)
    old_secret = secret.with_name(_SECRET_FILE_NAMES[0])
    if secret.name == _SECRET_FILE_NAMES[1] and old_secret.is_file():
        _rename(old_secret, secret)


def _move_daily_wire_login() -> None:
    from sources.dailywire.auth import DeviceAuthClient

    old_service, new_service = _KEYRING_SERVICES
    try:
        key = DeviceAuthClient().make_store_key()
        login = keyring.get_password(old_service, key)
        if login is None:
            return
        if keyring.get_password(new_service, key) is None:
            keyring.set_password(new_service, key, login)
        keyring.delete_password(old_service, key)
    except (KeyringError, RuntimeError) as exc:
        # Without a usable keyring there is no stored login to move.
        logger.warning("Could not move the Daily Wire login to the VODLoft keyring service: %s", exc)


async def _wait_for_startup_recovery(context) -> None:
    """Startup recovers the download folders in the background. Rename only after it has finished."""
    from backend.services.download_recovery import STARTUP_RECOVERY_PAUSE_OWNER
    from task_manager.scheduler.scheduler import scheduled_work_is_paused_by

    while scheduled_work_is_paused_by(STARTUP_RECOVERY_PAUSE_OWNER):
        context.raise_if_cancelled()
        await asyncio.sleep(_RECOVERY_POLL_SECONDS)


async def migrate(context) -> None:
    from backend.services.download_recovery import recover_download_filesystem

    context.raise_if_cancelled()
    context.update_progress(0, 4, "Moving the Daily Wire login and secret key")
    await asyncio.to_thread(_move_daily_wire_login)
    await asyncio.to_thread(_rename_secret_file)

    context.raise_if_cancelled()
    context.update_progress(1, 4, "Waiting for the download folder recovery to finish")
    await _wait_for_startup_recovery(context)

    context.update_progress(2, 4, "Renaming files in the download folders")
    await asyncio.to_thread(_rename_default_temporary_root)
    download_settings = get_settings().download_settings
    roots = {Path(download_settings.download_root), Path(download_settings.temporary_download_root)}
    configured = roots | {Path(download_settings.rss_cache_root)}
    for root in sorted(roots):
        context.raise_if_cancelled()
        if root.is_dir():
            renamed = await asyncio.to_thread(_rename_tree, root, configured=configured)
            logger.info("Renamed %s WireLoft files and folders in %s", renamed, root)

    context.update_progress(3, 4, "Finishing downloads that were interrupted")
    await asyncio.to_thread(recover_download_filesystem, download_settings)
    context.update_progress(4, 4, "Renamed WireLoft files")
