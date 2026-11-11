"""The database clears a download's link to its Download Profile when the profile is deleted.

VODLoft used to clear the link itself, one download at a time, before it deleted the profile.

Revision ID: 3f9c1e7a5b24
Revises: d7e173de7e72
Create Date: 2026-11-11
"""
from __future__ import annotations

from alembic import op

revision = "3f9c1e7a5b24"
down_revision = "d7e173de7e72"
branch_labels = None
depends_on = None

_NAME = "fk_media_downloads_episode_download_profile_id_download_profiles"


def _set_ondelete(ondelete: str | None) -> None:
    with op.batch_alter_table("media_downloads_episode") as batch:
        batch.drop_constraint(_NAME, type_="foreignkey")
        batch.create_foreign_key(_NAME, "download_profiles", ["download_profile_id"], ["id"], ondelete=ondelete)


def upgrade() -> None:
    _set_ondelete("SET NULL")


def downgrade() -> None:
    _set_ondelete(None)
