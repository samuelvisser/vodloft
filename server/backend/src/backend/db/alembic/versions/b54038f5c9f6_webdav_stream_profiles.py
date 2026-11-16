"""Add WebDAV stream profiles: a read-only network folder laid out as a TV show.

Revision ID: b54038f5c9f6
Revises: ee6dab087875
Create Date: 2026-11-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "b54038f5c9f6"
down_revision = "ee6dab087875"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stream_profiles_webdav",
        sa.Column("id", sa.Integer(), sa.ForeignKey("stream_profiles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("folder_name", sa.String(), nullable=True, comment="The show's folder; empty uses the profile's title"),
        sa.Column(
            "season_folders", sa.String(16), nullable=False,
            comment="How the episodes are sorted into folders: a WebdavSeasonFolders value",
        ),
        sa.Column(
            "metadata_files", sa.String(32), nullable=False,
            comment="What is listed beside the episodes for media players: a WebdavMetadataFiles value",
        ),
    )


def downgrade() -> None:
    op.drop_table("stream_profiles_webdav")
