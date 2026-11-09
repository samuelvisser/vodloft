"""Count how often each Collection page is opened, and remember how each user lists the Library.

The Library then lists the most used Collections first, unless a user picks another order.

Revision ID: 5b3a9f9d5b51
Revises: 4f7c2e9a1b38
Create Date: 2026-11-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "5b3a9f9d5b51"
down_revision = "4f7c2e9a1b38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "open_count", sa.Integer(), nullable=False, server_default="0",
            comment="How often the Collection's page was opened",
        ))
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column(
            "library_collection_sort", sa.String(), nullable=False, server_default="often_used",
            comment="How the user lists the Library's Collections: often_used, name, release_date or added_at",
        ))
        batch.add_column(sa.Column(
            "library_collection_sort_reversed", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="Whether the user turned that order around",
        ))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("library_collection_sort_reversed")
        batch.drop_column("library_collection_sort")
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("open_count")
