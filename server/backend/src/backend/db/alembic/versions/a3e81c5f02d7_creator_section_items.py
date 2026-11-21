"""Remember the videos of a creator's lists

A creator's collection leaves out the videos of the creator's lists, such as playlists, that are not in it.

Revision ID: a3e81c5f02d7
Revises: 7c4d2e9a1b36
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a3e81c5f02d7"
down_revision = "7c4d2e9a1b36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creator_section_items",
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("creator_sections.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_slug", sa.String(), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("creator_section_items")
