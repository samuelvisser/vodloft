"""Lists laid out by year.

A collection whose lists are seasons can lay them out in a season per upload year instead of a season each.

Revision ID: c47d2a91e5b8
Revises: 9b3e61d07a4f
Create Date: 2026-11-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "c47d2a91e5b8"
down_revision = "9b3e61d07a4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "list_layout", sa.String(), nullable=False, server_default="season_each",
            comment="How the lists that are seasons are laid out: season_each, or by_year in a season per upload year",
        ))


def downgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("list_layout")
