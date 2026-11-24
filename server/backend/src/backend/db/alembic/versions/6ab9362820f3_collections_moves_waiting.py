"""Collections store how many of their downloads wait to be moved.

Revision ID: 6ab9362820f3
Revises: 5c1e8b7d3f20
Create Date: 2026-11-24

Home and the Library read the count instead of working it out for every collection. A background migration counts
them once for the collections that are already there.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "6ab9362820f3"
down_revision = "5c1e8b7d3f20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collections", sa.Column(
        "moves_waiting", sa.Integer(), nullable=False, server_default="0",
        comment="How many of its downloads its season settings put in another season, which wait for its Move action; "
                "kept up to date whenever its videos are placed, and checked every night",
    ))


def downgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("moves_waiting")
