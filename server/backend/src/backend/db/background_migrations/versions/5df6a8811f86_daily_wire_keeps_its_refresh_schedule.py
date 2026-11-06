"""Keep The Daily Wire on the refresh schedule the user set.

Until now one schedule, from the config file, applied to every episode, and only
The Daily Wire's were refreshed. That setting is now the system schedule, which
Sites without a schedule of their own follow, and The Daily Wire has its own. A
schedule the user set in the config file therefore also becomes The Daily Wire's,
under ``siteSchedules``, so its episodes are refreshed as before. Changing the
config file is why this is not part of the database migration.

Revision ID: 5df6a8811f86
Revises: 7ffa406cf785
"""

from __future__ import annotations

from pathlib import Path
import json
import os
import stat
import tempfile

import yaml

from config import get_settings
from config.registry import reload_settings
from config.settings.base import get_config_path


revision = "5df6a8811f86"
down_revision = "7ffa406cf785"
title = "Keep The Daily Wire on its refresh schedule"

# The system schedule VODLoft ships. A config file without a schedule of its own has it,
# and The Daily Wire then keeps the schedule it always had, which is now its default.
_SYSTEM_DEFAULT = "1h,6h,24h,3d"
_SECTIONS = {"siteSchedules", "site_schedules"}


def _with_daily_wire_schedule(source: str, schedule: str) -> str:
    """Add The Daily Wire's schedule at the end, unless the file already schedules Sites itself."""
    document = yaml.safe_load(source) if source.strip() else {}
    if not isinstance(document, dict) or _SECTIONS & set(document):
        return source
    if source and not source.endswith("\n"):
        source += "\n"
    return source + f"siteSchedules:\n  dailywire:\n    metadataRefresh: {json.dumps(schedule)}\n"


async def migrate(context) -> None:
    context.raise_if_canceled()
    configured = get_settings().new_episode_schedule.metadata_refresh_intervals
    context.update_progress(0, 1, "Keeping The Daily Wire on its refresh schedule")
    if configured == _SYSTEM_DEFAULT:
        return
    path = get_config_path()
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        original = ""

    updated = _with_daily_wire_schedule(original, configured)
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

        if path.exists():
            temporary_path.chmod(stat.S_IMODE(path.stat().st_mode))
        context.raise_if_canceled()
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)

    reload_settings()
    context.update_progress(1, 1, "Keeping The Daily Wire on its refresh schedule")
