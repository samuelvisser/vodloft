"""Let a Download Profile download every season, without a seasons line, and filter on seasons in its own lines.

Revision ID: ce5df2342e6f
Revises: 158c03681e52
Create Date: 2026-11-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ce5df2342e6f"
down_revision = "158c03681e52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column(
            "all_seasons", sa.Boolean(), server_default="0", nullable=False,
            comment="The seasons line was removed: every season downloads, upcoming ones included",
        ))
    with op.batch_alter_table("download_profile_rules") as batch:
        batch.add_column(sa.Column("season_slugs", sa.JSON(), nullable=True, comment="The season slugs of a seasons rule"))


def downgrade() -> None:
    op.execute("DELETE FROM download_profile_rules WHERE field = 'seasons'")
    with op.batch_alter_table("download_profile_rules") as batch:
        batch.drop_column("season_slugs")
    with op.batch_alter_table("download_profiles") as batch:
        batch.drop_column("all_seasons")
