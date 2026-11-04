"""Let a Download Profile download every season, without a seasons line.

Revision ID: ce5df2342e6f
Revises: 7b3e9d2a4c61
Create Date: 2026-11-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ce5df2342e6f"
down_revision = "7b3e9d2a4c61"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column(
            "all_seasons", sa.Boolean(), server_default="0", nullable=False,
            comment="The seasons line was removed: every season downloads, upcoming ones included",
        ))


def downgrade() -> None:
    with op.batch_alter_table("download_profiles") as batch:
        batch.drop_column("all_seasons")
