"""Let a collection without a link of its own take its picture from the link the user chooses.

Revision ID: 0e8510a81f57
Revises: 8a47bfd00213
Create Date: 2026-11-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0e8510a81f57"
down_revision = "8a47bfd00213"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("collection_lists") as batch:
        batch.add_column(sa.Column(
            "picture", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="Its picture is the collection's, for a collection without a link of its own; one at most per collection",
        ))


def downgrade() -> None:
    with op.batch_alter_table("collection_lists") as batch:
        batch.drop_column("picture")
