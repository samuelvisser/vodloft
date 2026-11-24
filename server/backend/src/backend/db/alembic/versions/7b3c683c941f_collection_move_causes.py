"""Collections store why their downloads wait for the Move action.

Revision ID: 7b3c683c941f
Revises: 917089ea3b82
Create Date: 2026-11-24

The setting changes that put a collection's downloads in another season, which the Move dialog shows. Downloads that
wait already have none recorded.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "7b3c683c941f"
down_revision = "917089ea3b82"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collections", sa.Column(
        "move_causes", sa.JSON(), nullable=False, server_default="[]",
        comment="The setting changes that put its downloads in another season, which wait for its Move action: each "
                "setting as it was before and is now, by where it is changed, such as its Seasons dialog. Empty once "
                "nothing waits, or when none was recorded",
    ))


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("collections") as batch:
            batch.drop_column("move_causes")
    else:
        op.drop_column("collections", "move_causes")
