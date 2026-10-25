"""Record which Source every show and media item comes from.

Revision ID: a3e7c1d9f052
Revises: a4e7c19b2d53
Create Date: 2026-10-25

Everything stored before VODLoft had Sources came from The Daily Wire.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a3e7c1d9f052"
down_revision = "a4e7c19b2d53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("shows", "media_items"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("source_key", sa.String(), nullable=False, server_default="dailywire", comment="Id of the Source this comes from, as registered in sources"))
            batch.create_index(f"ix_{table}_source_key", ["source_key"])


def downgrade() -> None:
    for table in ("shows", "media_items"):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_source_key")
            batch.drop_column("source_key")
