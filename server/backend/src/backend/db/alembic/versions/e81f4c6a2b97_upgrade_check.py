"""The upgrade check on Download Profiles, and what a download kept.

Existing profiles start with the upgrade check off; new ones start with it on.

Revision ID: e81f4c6a2b97
Revises: c5d82b19e4a6
Create Date: 2026-11-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "e81f4c6a2b97"
down_revision = "c5d82b19e4a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column("upgrade_check", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column(
            "upgrade_after_days", sa.Integer(), nullable=False, server_default="7",
            comment="Days after downloading that the upgrade check first looks",
        ))
        batch.add_column(sa.Column(
            "upgrade_repeat", sa.String(16), nullable=False, server_default="once",
            comment="once, twice (again after 30 days) or every (up to 3 times)",
        ))
        batch.add_column(sa.Column(
            "upgrade_improvements", sa.JSON(), nullable=False, server_default='["resolution", "sponsorblock"]',
            comment="What counts as a better version: resolution, sponsorblock, subtitles or codec",
        ))
    with op.batch_alter_table("media_downloads") as batch:
        batch.add_column(sa.Column("video_height", sa.Integer(), nullable=True, comment="The smaller side of the kept video stream, in pixels"))
        batch.add_column(sa.Column("video_codec", sa.String(20), nullable=True, comment="The codec of the kept video stream"))
        batch.add_column(sa.Column(
            "subtitle_languages", sa.JSON(), nullable=True, comment="The languages of the site's own subtitles the download kept",
        ))
    with op.batch_alter_table("media_downloads_episode") as batch:
        batch.add_column(sa.Column(
            "upgrade_checks", sa.Integer(), nullable=False, server_default="0",
            comment="How many times the upgrade check has looked at this download",
        ))
        batch.add_column(sa.Column(
            "upgrade_check_at", sa.DateTime(), nullable=True, comment="When the upgrade check looks next; empty when it will not",
        ))
        batch.add_column(sa.Column(
            "upgrade_result", sa.String(16), nullable=True, comment="What the last upgrade check found: upgraded or checked",
        ))


def downgrade() -> None:
    with op.batch_alter_table("media_downloads_episode") as batch:
        batch.drop_column("upgrade_result")
        batch.drop_column("upgrade_check_at")
        batch.drop_column("upgrade_checks")
    with op.batch_alter_table("media_downloads") as batch:
        batch.drop_column("subtitle_languages")
        batch.drop_column("video_codec")
        batch.drop_column("video_height")
    with op.batch_alter_table("download_profiles") as batch:
        batch.drop_column("upgrade_improvements")
        batch.drop_column("upgrade_repeat")
        batch.drop_column("upgrade_after_days")
        batch.drop_column("upgrade_check")
