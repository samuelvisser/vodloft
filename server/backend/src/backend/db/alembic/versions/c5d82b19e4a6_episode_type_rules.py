"""A filter in Which episodes can look at the episode type.

Skip and Keep filters on episode types need the types they match.

Revision ID: c5d82b19e4a6
Revises: a93c6e0d1f27
Create Date: 2026-11-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "c5d82b19e4a6"
down_revision = "a93c6e0d1f27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("download_profile_rules") as batch:
        batch.add_column(sa.Column("episode_types", sa.JSON(), nullable=True, comment="The episode type keys of a types rule"))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM download_profile_rules WHERE field = 'types'"))
    with op.batch_alter_table("download_profile_rules") as batch:
        batch.drop_column("episode_types")
