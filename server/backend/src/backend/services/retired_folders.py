"""Remove the folders VODLoft managed under a folder setting that has since changed.

At every start VODLoft compares the folder settings below with the folders it
used last time, which it remembers in ``folders.json`` next to the config file.
A folder that is no longer configured is removed, but only when it is one that
VODLoft alone manages: a hidden ``.vodloft-*`` folder, or the setting's own
default. Anything else, such as ``/tmp`` or a folder of the user's own, keeps
its contents and stays where it is. The download root is never touched.

Quick downloads and thumbnails move to the new folder first, so a ready file
or a thumbnail is not lost. Startup runs this while no download runs, so a
download that was staged in the old temporary folder is reconciled before the
folder goes.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from config.settings.base import get_config_path

logger = logging.getLogger(__name__)

# Settings whose folder holds only what VODLoft put there.
_MANAGED_FOLDER_SETTINGS = (
    "temporary_download_root",
    "rss_cache_root",
    "quick_download_root",
    "thumbnail_root",
    "lock_root",
)
# Settings whose contents should outlive a move.
_MOVED_CONTENTS = frozenset({"quick_download_root", "thumbnail_root"})
_MANAGED_NAME_PREFIX = ".vodloft-"


def _state_path() -> Path:
    return get_config_path().parent / "folders.json"


def _load_state() -> dict[str, str]:
    try:
        stored = json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(stored, dict):
        return {}
    return {key: value for key, value in stored.items() if isinstance(value, str) and value}


def _store_state(state: dict[str, str]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".folders-", suffix=".tmp", delete=False) as file:
        json.dump(state, file, indent=2, sort_keys=True)
    os.replace(file.name, path)


def _default_folder(download_settings, setting: str) -> Path:
    field = type(download_settings).model_fields[setting]
    return Path(field.get_default(
        call_default_factory=True,
        validated_data={"download_root": Path(download_settings.download_root)},
    ))


def _is_vodloft_folder(download_settings, setting: str, folder: Path) -> bool:
    return folder.name.startswith(_MANAGED_NAME_PREFIX) or folder == _default_folder(download_settings, setting)


def _may_remove(download_settings, setting: str, folder: Path) -> bool:
    if folder.is_symlink() or not folder.is_dir():
        return False
    if not _is_vodloft_folder(download_settings, setting, folder):
        logger.info("Left the former %s folder %s in place, because VODLoft does not manage it alone", setting, folder)
        return False
    resolved = folder.resolve()
    # A folder inside the download root or the config folder may go, but never one that holds either.
    for root in (Path(download_settings.download_root).resolve(), get_config_path().parent.resolve()):
        if root.is_relative_to(resolved):
            logger.info("Left the former %s folder %s in place, because it holds %s", setting, folder, root)
            return False
    # Nor one that is, holds or sits in a folder VODLoft uses now.
    for current_setting in _MANAGED_FOLDER_SETTINGS:
        current = Path(getattr(download_settings, current_setting)).resolve()
        if resolved == current or resolved.is_relative_to(current) or current.is_relative_to(resolved):
            logger.info("Left the former %s folder %s in place, because it overlaps %s", setting, folder, current)
            return False
    return True


def _move_contents(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        destination = target / entry.name
        if destination.exists() or destination.is_symlink():
            continue
        try:
            shutil.move(entry, destination)
        except OSError as exc:
            logger.warning("Could not move %s to %s: %s", entry, destination, exc)


def _retire(download_settings, setting: str, folder: Path) -> bool:
    """Remove one former folder. Return whether it is gone, so it need not be tried again."""
    if not folder.exists() and not folder.is_symlink():
        return True
    if not _may_remove(download_settings, setting, folder):
        return True
    if setting == "temporary_download_root":
        from backend.services.download_recovery import cleanup_abandoned_temporary_downloads

        # Publish or roll back what an interrupted download left staged there.
        cleanup_abandoned_temporary_downloads(folder, download_settings.download_root)
    if setting in _MOVED_CONTENTS:
        _move_contents(folder, Path(getattr(download_settings, setting)))
    try:
        shutil.rmtree(folder)
    except OSError as exc:
        logger.warning("Could not remove the former %s folder %s: %s", setting, folder, exc)
        return False
    logger.info("Removed the former %s folder %s", setting, folder)
    return True


def retire_changed_folders(download_settings) -> int:
    """Remove the managed folders of settings that changed since the last start. Run it while no download runs."""
    previous = _load_state()
    current = {setting: str(getattr(download_settings, setting)) for setting in _MANAGED_FOLDER_SETTINGS}
    removed = 0
    kept: dict[str, str] = {}
    for setting, folder in previous.items():
        if setting.startswith("retired:"):
            name = setting.removeprefix("retired:")
        elif setting in current and folder != current[setting]:
            name = setting
        else:
            continue
        if Path(folder) == Path(current.get(name, "")):
            continue
        existed = Path(folder).is_dir()
        if _retire(download_settings, name, Path(folder)):
            removed += existed and not Path(folder).exists()
        else:
            # Try again at the next start.
            kept[f"retired:{name}"] = folder
    _store_state({**kept, **current})
    return removed
