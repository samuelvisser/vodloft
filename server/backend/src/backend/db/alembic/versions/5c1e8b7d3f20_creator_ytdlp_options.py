"""A creator's own yt-dlp options, for every collection of the creator on a Site that takes yt-dlp options.

Revision ID: 5c1e8b7d3f20
Revises: ee7b43f4d6a1
Create Date: 2026-11-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "5c1e8b7d3f20"
down_revision = "ee7b43f4d6a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("creators", sa.Column(
        "ytdlp_options", sa.Text(), nullable=False, server_default="",
        comment="Your own yt-dlp options for the creator's collections, after the yt-dlp Source's and before each collection's own",
    ))


def downgrade() -> None:
    with op.batch_alter_table("creators") as batch:
        batch.drop_column("ytdlp_options")
