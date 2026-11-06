"""Each Site chooses how often its upcoming and live episodes are looked up.

Revision ID: 4b9e2d7c1a63
Revises: 7c3e9a1f5b2d
Create Date: 2026-11-06

Every Source follows one rhythm for upcoming and live episodes: every hour while
upcoming, often around the start, and every few minutes while live. Each Site
keeps its own copy of those intervals, starting at the usual ones.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "4b9e2d7c1a63"
down_revision = "7c3e9a1f5b2d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.add_column(sa.Column(
            "pending_upcoming_minutes", sa.Integer(), nullable=False, server_default="60",
            comment="Minutes between lookups of an upcoming episode",
        ))
        batch.add_column(sa.Column(
            "pending_starting_minutes", sa.Integer(), nullable=False, server_default="2",
            comment="Minutes between lookups from 15 minutes before an episode starts until an hour after",
        ))
        batch.add_column(sa.Column(
            "pending_live_minutes", sa.Integer(), nullable=False, server_default="5",
            comment="Minutes between lookups while an episode is live or still being finished",
        ))


def downgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.drop_column("pending_live_minutes")
        batch.drop_column("pending_starting_minutes")
        batch.drop_column("pending_upcoming_minutes")
