"""SponsorBlock on Download Profiles, the segments of each download, and your own yt-dlp options.

Revision ID: b5e1c0a7d392
Revises: 7d3a90b2c4e1
Create Date: 2026-11-03
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "b5e1c0a7d392"
down_revision = "7d3a90b2c4e1"
branch_labels = None
depends_on = None

_DEFAULT_SEGMENTS = {
    "sponsor": "cut", "selfpromo": "cut", "interaction": "cut",
    "intro": "chapter", "outro": "chapter", "preview": "chapter",
    "filler": "keep", "music_offtopic": "keep",
}


def upgrade() -> None:
    with op.batch_alter_table("download_profiles") as batch:
        # Existing profiles keep downloading the whole video until SponsorBlock is switched on.
        batch.add_column(sa.Column("sponsorblock_enabled", sa.Boolean(), server_default="0", nullable=False))
        batch.add_column(sa.Column(
            "sponsorblock_segments", sa.JSON(), server_default=json.dumps(_DEFAULT_SEGMENTS), nullable=False,
            comment="SponsorBlock segment type to keep, chapter or cut, for YouTube Collections",
        ))
    with op.batch_alter_table("download_profiles") as batch:
        batch.alter_column("sponsorblock_segments", server_default=None)
    with op.batch_alter_table("media_downloads") as batch:
        batch.add_column(sa.Column(
            "sponsorblock_segments", sa.JSON(), nullable=True,
            comment="The SponsorBlock segments of the video as published, and whether each became a chapter or was cut",
        ))
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column(
            "ytdlp_options", sa.Text(), server_default="", nullable=False,
            comment="Your own yt-dlp options, one or more per line, for downloads yt-dlp makes",
        ))
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "ytdlp_options", sa.Text(), server_default="", nullable=False,
            comment="Your own yt-dlp options for this Collection, added after the Local Media Profile's",
        ))


def downgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("ytdlp_options")
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("ytdlp_options")
    with op.batch_alter_table("media_downloads") as batch:
        batch.drop_column("sponsorblock_segments")
    with op.batch_alter_table("download_profiles") as batch:
        batch.drop_column("sponsorblock_segments")
        batch.drop_column("sponsorblock_enabled")
