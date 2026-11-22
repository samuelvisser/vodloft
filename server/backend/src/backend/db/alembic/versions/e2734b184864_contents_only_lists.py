"""A list of a collection can add its videos without being a season of its own.

The simple creators migration (295b85b20467) first dropped ``collection_lists.as_season``; it now keeps it. A database
that already ran the earlier version gets the column back here, with every list a season, as that version left them.

Revision ID: e2734b184864
Revises: 295b85b20467
Create Date: 2026-11-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "e2734b184864"
down_revision = "295b85b20467"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("collection_lists")}
    if "as_season" in columns:
        return
    with op.batch_alter_table("collection_lists") as batch:
        batch.add_column(sa.Column(
            "as_season", sa.Boolean(), nullable=False, server_default=sa.true(),
            comment="Whether the list is a season of its own, or its videos join the collection's other seasons",
        ))


def downgrade() -> None:
    # 295b85b20467 keeps the column, so going back to it keeps it too.
    pass
