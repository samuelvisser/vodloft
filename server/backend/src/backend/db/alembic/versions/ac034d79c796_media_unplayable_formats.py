"""Media that yt-dlp only downloads with --allow-unplayable-formats, for another reason than DRM.

Revision ID: ac034d79c796
Revises: 4c7e19a2b6d0
Create Date: 2026-11-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "ac034d79c796"
down_revision = "4c7e19a2b6d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_items", sa.Column(
        "unplayable_formats", sa.Boolean(), nullable=False, server_default=sa.false(),
        comment="yt-dlp found no playable formats for the media for another reason than DRM",
    ))


def downgrade() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("unplayable_formats")
