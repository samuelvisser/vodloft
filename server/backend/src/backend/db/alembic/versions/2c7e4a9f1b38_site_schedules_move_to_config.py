"""A Site's own scheduling moves to config.yml.

Revision ID: 2c7e4a9f1b38
Revises: 9d1f3b6a2c84
Create Date: 2026-11-06

Each Site's metadata refresh schedule and upcoming and live settings are now kept under
``siteSchedules`` in config.yml, next to the system settings they fall back to, so the
Site rows no longer hold them. None of these columns shipped in a release.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "2c7e4a9f1b38"
down_revision = "9d1f3b6a2c84"
branch_labels = None
depends_on = None

_MINUTES = ("pending_upcoming_minutes", "pending_starting_minutes", "pending_live_minutes")


def upgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        for name in ("refresh_mode", "refresh_intervals", "pending_checks", *_MINUTES):
            batch.drop_column(name)


def downgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.add_column(sa.Column("refresh_mode", sa.String(), nullable=False, server_default="system"))
        batch.add_column(sa.Column("refresh_intervals", sa.String(), nullable=True))
        batch.add_column(sa.Column("pending_checks", sa.Boolean(), nullable=True))
        for name in _MINUTES:
            batch.add_column(sa.Column(name, sa.Integer(), nullable=True))
