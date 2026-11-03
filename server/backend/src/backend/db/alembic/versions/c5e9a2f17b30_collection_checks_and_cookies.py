"""Per-Collection check frequency and cookies.

Revision ID: c5e9a2f17b30
Revises: b3d7e1f04a62
Create Date: 2026-11-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "c5e9a2f17b30"
down_revision = "b3d7e1f04a62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "cookies_mode", sa.String(), nullable=False, server_default="automatic",
            comment="When downloads use the Source's cookies file: automatic, never or always",
        ))
        batch.add_column(sa.Column(
            "cookies_needed_until", sa.DateTime(), nullable=True,
            comment="Automatic cookies: downloads use the cookies file until then",
        ))
        batch.add_column(sa.Column(
            "check_frequency", sa.String(), nullable=False, server_default="default",
            comment="How often VODLoft looks for new episodes: default, less_often or own",
        ))
        batch.add_column(sa.Column(
            "check_cron", sa.String(), nullable=True, comment="The Collection's own schedule, with check_frequency own",
        ))


def downgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("check_cron")
        batch.drop_column("check_frequency")
        batch.drop_column("cookies_needed_until")
        batch.drop_column("cookies_mode")
