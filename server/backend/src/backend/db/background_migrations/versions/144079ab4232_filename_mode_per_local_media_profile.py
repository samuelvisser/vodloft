"""Give every Local Media Profile the filename mode Settings had.

Revision ID: 144079ab4232
Revises: 875ce72375ca

The filename mode moved from Settings onto each Local Media Profile; the mode in Settings is now
what a new profile starts with. The database migration could not read config.yml, so existing
profiles start as Windows-compatible until this gives them the mode their files were named with.
"""

from __future__ import annotations

from sqlalchemy import update

from backend.db.core import run_write_transaction
from backend.db.models import LocalMediaProfileBase
from config import get_settings
from config.settings.submodels import FilenameRestrictionMode


revision = "144079ab4232"
down_revision = "875ce72375ca"
title = "Give every Local Media Profile the filename mode Settings had"


async def migrate(context) -> None:
    context.raise_if_canceled()
    mode = FilenameRestrictionMode(get_settings().download_settings.filename_restriction_mode).value
    run_write_transaction(lambda session: session.execute(
        update(LocalMediaProfileBase)
        .where(LocalMediaProfileBase.filename_restriction_mode != mode)
        .values(filename_restriction_mode=mode)
    ))
