"""Retention of manual downloads: a Download Profile that deletes older episodes can also delete the manual
downloads of its collection in its Local Media Profile.

Revision ID: 7c41e2a9d5b3
Revises: 03646be1903c
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7c41e2a9d5b3"
down_revision = "03646be1903c"
branch_labels = None
depends_on = None

COMMENT = (
    "Whether deleting older episodes also deletes the manual downloads of the collection in its Local Media Profile"
)


def upgrade() -> None:
    op.add_column("download_profiles", sa.Column(
        "retention_includes_manual", sa.Boolean(), nullable=False, server_default="0", comment=COMMENT,
    ))


def downgrade() -> None:
    with op.batch_alter_table("download_profiles") as batch:
        batch.drop_column("retention_includes_manual")
