"""The upgrade check can download a Daily Wire episode again when its length changed.

Each download remembers the length of its file, and a Download Profile how many minutes longer or
shorter count as a different length. Download Profiles of Daily Wire collections had no upgrade check
before; they get it, counting a different length as the better version.

Revision ID: d6346ad993ee
Revises: aa950d2ab545
Create Date: 2026-11-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d6346ad993ee"
down_revision = "aa950d2ab545"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_downloads") as batch:
        batch.add_column(sa.Column(
            "duration", sa.Float(), nullable=True,
            comment="The length of the downloaded file in seconds; the media item's duration is the length the site lists",
        ))
    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column(
            "upgrade_length_minutes", sa.Integer(), nullable=False, server_default="5",
            comment="How many minutes longer or shorter counts as a different length",
        ))
        batch.alter_column(
            "upgrade_improvements", existing_type=sa.JSON(), existing_nullable=False,
            comment="What counts as a better version: resolution, sponsorblock, subtitles, codec or length",
        )
    op.execute(sa.text(
        "UPDATE download_profiles SET upgrade_check = 1, upgrade_improvements = '[\"length\"]' "
        "WHERE collection_id IN (SELECT id FROM collections WHERE source_key = 'dailywire')"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE download_profiles SET upgrade_check = 0, upgrade_improvements = '[\"resolution\", \"sponsorblock\"]' "
        "WHERE collection_id IN (SELECT id FROM collections WHERE source_key = 'dailywire')"
    ))
    with op.batch_alter_table("download_profiles") as batch:
        batch.alter_column(
            "upgrade_improvements", existing_type=sa.JSON(), existing_nullable=False,
            comment="What counts as a better version: resolution, sponsorblock, subtitles or codec",
        )
        batch.drop_column("upgrade_length_minutes")
    with op.batch_alter_table("media_downloads") as batch:
        batch.drop_column("duration")
