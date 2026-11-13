"""A Site's upcoming and live settings follow the system setting unless it has its own.

Revision ID: 9d1f3b6a2c84
Revises: 4b9e2d7c1a63
Create Date: 2026-11-06

Whether a Site follows upcoming and live videos, and how often it looks them up, can now
be left to the system setting in config.yml. A Site that kept the usual values follows it
from now on; one that was changed keeps its own.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "9d1f3b6a2c84"
down_revision = "4b9e2d7c1a63"
branch_labels = None
depends_on = None

_MINUTES = ("pending_upcoming_minutes", "pending_starting_minutes", "pending_live_minutes")
_USUAL = (60, 2, 5)

sites = sa.table(
    "sites",
    sa.column("pending_checks", sa.Boolean()),
    *(sa.column(name, sa.Integer()) for name in _MINUTES),
)


def upgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.alter_column("pending_checks", existing_type=sa.Boolean(), nullable=True, server_default=None)
        for name in _MINUTES:
            batch.alter_column(name, existing_type=sa.Integer(), nullable=True, server_default=None)
    op.execute(sites.update().where(sites.c.pending_checks == sa.true()).values(pending_checks=None))
    op.execute(
        sites.update()
        .where(*(sites.c[name] == value for name, value in zip(_MINUTES, _USUAL)))
        .values({name: None for name in _MINUTES})
    )


def downgrade() -> None:
    op.execute(sites.update().where(sites.c.pending_checks.is_(None)).values(pending_checks=sa.true()))
    for name, value in zip(_MINUTES, _USUAL):
        op.execute(sites.update().where(sites.c[name].is_(None)).values({name: value}))
    with op.batch_alter_table("sites") as batch:
        batch.alter_column("pending_checks", existing_type=sa.Boolean(), nullable=False, server_default="1")
        for name, value in zip(_MINUTES, _USUAL):
            batch.alter_column(name, existing_type=sa.Integer(), nullable=False, server_default=str(value))
