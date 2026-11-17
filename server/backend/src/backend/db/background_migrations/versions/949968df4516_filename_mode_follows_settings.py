"""Let Local Media Profiles with the filename mode in Settings follow Settings.

Revision ID: 949968df4516
Revises: 144079ab4232

A Local Media Profile's filename mode can now be System, which follows Settings, and new profiles start
with it. A profile that has the same mode as Settings follows Settings from now on, so its files keep
their names.
"""

from __future__ import annotations

from sqlalchemy import update

from backend.db.core import run_write_transaction
from backend.db.models import LocalMediaProfileBase
from backend.types.local_media_profile_types import LocalMediaProfileFilenameMode
from config import get_settings
from config.settings.submodels import FilenameRestrictionMode


revision = "949968df4516"
down_revision = "144079ab4232"
title = "Let Local Media Profiles with the filename mode in Settings follow Settings"


async def migrate(context) -> None:
    context.raise_if_canceled()
    mode = FilenameRestrictionMode(get_settings().download_settings.filename_restriction_mode).value
    run_write_transaction(lambda session: session.execute(
        update(LocalMediaProfileBase)
        .where(LocalMediaProfileBase.filename_restriction_mode == mode)
        .values(filename_restriction_mode=LocalMediaProfileFilenameMode.SYSTEM.value)
    ))
