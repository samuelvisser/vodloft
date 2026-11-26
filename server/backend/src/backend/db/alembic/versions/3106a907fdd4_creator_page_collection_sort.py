"""Each user's order for the collections on a creator page, apart from the Library's.

Revision ID: 3106a907fdd4
Revises: d0386f2772fc
Create Date: 2026-11-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "3106a907fdd4"
down_revision = "d0386f2772fc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "creator_collection_sort", sa.String(), nullable=False, server_default="recently_used",
        comment="How the user lists a creator page's Collections: recently_used, often_used, name, release_date or added_at",
    ))
    op.add_column("users", sa.Column(
        "creator_collection_sort_reversed", sa.Boolean(), nullable=False, server_default=sa.false(),
        comment="Whether the user turned that order around",
    ))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("creator_collection_sort_reversed")
        batch.drop_column("creator_collection_sort")
