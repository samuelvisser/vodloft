"""Remember when each Collection page was last opened, for the Library's Recently used order.

Revision ID: 9c4e1a7d2f60
Revises: 5b3a9f9d5b51
Create Date: 2026-11-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9c4e1a7d2f60"
down_revision = "5b3a9f9d5b51"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "last_opened_at", sa.DateTime(timezone=True), nullable=True,
            comment="When the Collection's page was last opened",
        ))
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "library_collection_sort", existing_type=sa.String(), existing_nullable=False,
            existing_server_default="often_used",
            comment="How the user lists the Library's Collections: often_used, recently_used, name, release_date or added_at",
            existing_comment="How the user lists the Library's Collections: often_used, name, release_date or added_at",
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "library_collection_sort", existing_type=sa.String(), existing_nullable=False,
            existing_server_default="often_used",
            comment="How the user lists the Library's Collections: often_used, name, release_date or added_at",
            existing_comment="How the user lists the Library's Collections: often_used, recently_used, name, release_date or added_at",
        )
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("last_opened_at")
