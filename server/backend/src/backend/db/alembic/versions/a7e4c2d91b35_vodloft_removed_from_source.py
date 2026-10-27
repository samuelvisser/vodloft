"""Mark media that its Source no longer has, such as a video deleted from YouTube.

Revision ID: a7e4c2d91b35
Revises: f4abb559e3ab
Create Date: 2026-10-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a7e4c2d91b35"
down_revision = "f4abb559e3ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(sa.Column(
            "removed_from_source", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="The Source no longer has the media; downloaded files are kept",
        ))


def downgrade() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("removed_from_source")
