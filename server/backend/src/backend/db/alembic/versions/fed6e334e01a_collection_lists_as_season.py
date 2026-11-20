"""Let a list be in a collection without being a season

A creator's list can be in the creator's own collection with its videos in the collection's other seasons, rather
than as a season of its own.

Revision ID: fed6e334e01a
Revises: a3e81c5f02d7
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "fed6e334e01a"
down_revision = "a3e81c5f02d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collection_lists", sa.Column("as_season", sa.Boolean(), nullable=False, server_default="1"))


def downgrade() -> None:
    with op.batch_alter_table("collection_lists") as batch:
        batch.drop_column("as_season")
