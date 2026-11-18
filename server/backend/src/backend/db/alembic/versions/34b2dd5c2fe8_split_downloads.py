"""Split downloads: a collection can split each new video with chapters into a part per chapter, and an episode
remembers which video and which stretch of it it is.

Revision ID: 34b2dd5c2fe8
Revises: 4737d5b6dd34
Create Date: 2026-11-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "34b2dd5c2fe8"
down_revision = "4737d5b6dd34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "split_chapters", sa.Boolean(), nullable=False, server_default="0",
            comment="Each new video with chapters becomes a season of its own, with an episode per chapter",
        ))
    with op.batch_alter_table("media_items_episode") as batch:
        batch.add_column(sa.Column(
            "part_of", sa.String(), nullable=True,
            comment="The Source's slug of the video the episode is one part of, when its collection splits videos by chapter",
        ))
        batch.add_column(sa.Column("part_start", sa.Float(), nullable=True, comment="Where the part starts in its video, in seconds"))
        batch.add_column(sa.Column("part_end", sa.Float(), nullable=True, comment="Where the part ends in its video, in seconds"))


def downgrade() -> None:
    with op.batch_alter_table("media_items_episode") as batch:
        batch.drop_column("part_end")
        batch.drop_column("part_start")
        batch.drop_column("part_of")
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("split_chapters")
