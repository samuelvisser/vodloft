"""VODLoft 0.10.1's additions.

A Local Media Profile can keep the chapters a video comes with, cut out chapters by their title, and save the
site's info file beside the media. A Collection profile can give episodes a title and description of its own
in their metadata. A Download Profile's published line can end on a date.

Profiles that already exist keep doing what they did: they leave the chapters out unless SponsorBlock adds
some. New profiles start with the chapters kept.

Revision ID: 8340278b15a0
Revises: 5e8f0b3c6d21
Create Date: 2026-11-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "8340278b15a0"
down_revision = "5e8f0b3c6d21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("local_media_profiles", sa.Column(
        "keep_chapters", sa.Boolean(), nullable=False, server_default=sa.false(),
        comment="Keep the chapters the video comes with",
    ))
    op.add_column("local_media_profiles", sa.Column(
        "cut_chapters", sa.JSON(), nullable=False, server_default="[]",
        comment="Regular expressions: a chapter whose title matches one is cut out",
    ))
    op.add_column("local_media_profiles", sa.Column(
        "save_info_json", sa.Boolean(), nullable=False, server_default=sa.false(),
        comment="Save the site's info file, which yt-dlp writes, beside the media",
    ))
    for name, what in (("episode_title_template", "title"), ("episode_description_template", "description")):
        op.add_column("local_media_profiles_collection", sa.Column(
            name, sa.Text(), nullable=True,
            comment=f"A Jinja template for each episode's {what} in its NFO and embedded metadata",
        ))
    op.add_column("local_media_profiles_collection", sa.Column(
        "episode_nfo", sa.String(16), nullable=False, server_default="episode",
        comment="What each episode's NFO file and embedded metadata call it: episode or music_video",
    ))
    op.add_column("download_profile_filters", sa.Column(
        "until", sa.Date(), nullable=True, comment="A published line: published on or before this day",
    ))
    op.add_column("media_downloads", sa.Column(
        "cut_chapters", sa.JSON(), nullable=True,
        comment="The chapters of the video as published that were cut out by their title",
    ))


def downgrade() -> None:
    with op.batch_alter_table("local_media_profiles_collection") as batch:
        batch.drop_column("episode_description_template")
        batch.drop_column("episode_title_template")
        batch.drop_column("episode_nfo")
    with op.batch_alter_table("download_profile_filters") as batch:
        batch.drop_column("until")
    with op.batch_alter_table("media_downloads") as batch:
        batch.drop_column("cut_chapters")
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("save_info_json")
        batch.drop_column("cut_chapters")
        batch.drop_column("keep_chapters")
