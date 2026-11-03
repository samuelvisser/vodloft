"""Quality goals, codecs and audio language; subtitle languages; auto-generated subtitles.

Revision ID: 7d3a90b2c4e1
Revises: 1c60d6815b6b
Create Date: 2026-11-02
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "7d3a90b2c4e1"
down_revision = "1c60d6815b6b"
branch_labels = None
depends_on = None

# What VODLoft downloaded before goals existed: H.264 when there is one, otherwise the best there is.
_COMPATIBILITY = [
    {"codec": "h264", "allowed": True}, {"codec": "av1", "allowed": False},
    {"codec": "vp9", "allowed": False}, {"codec": "h265", "allowed": False},
]
# Above 1080p there is rarely H.264, so a 4K profile took VP9 or AV1 in MP4.
_PREFER_H264 = [
    {"codec": "h264", "allowed": True}, {"codec": "vp9", "allowed": True},
    {"codec": "av1", "allowed": True}, {"codec": "h265", "allowed": True},
]


def upgrade() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column("subtitle_languages", sa.JSON(), server_default='["en"]', nullable=False))
        batch.add_column(sa.Column("subtitle_language_mode", sa.String(16), server_default="listed", nullable=False))
        batch.add_column(sa.Column("quality_goal", sa.String(16), server_default="compatibility", nullable=False))
        batch.add_column(sa.Column("video_codecs", sa.JSON(), server_default=json.dumps(_COMPATIBILITY), nullable=False))
        batch.add_column(sa.Column("codec_fallback", sa.String(8), server_default="best", nullable=False))
        batch.add_column(sa.Column("container", sa.String(8), server_default="mp4", nullable=False))
        batch.add_column(sa.Column("audio_codec", sa.String(8), server_default="aac", nullable=False))
        batch.add_column(sa.Column("audio_format", sa.String(8), server_default="m4a", nullable=False))
        batch.add_column(sa.Column("audio_language", sa.String(16), nullable=True))
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.alter_column("video_codecs", server_default=None)
    profiles = sa.table(
        "local_media_profiles",
        sa.column("preferred_format", sa.String()), sa.column("subtitle_language_mode", sa.String()),
        sa.column("quality_goal", sa.String()), sa.column("video_codecs", sa.JSON()),
    )
    # Existing profiles keep downloading every subtitle language the site has.
    op.execute(profiles.update().values(subtitle_language_mode="site"))
    op.execute(
        profiles.update().where(profiles.c.preferred_format == "format_4k")
        .values(quality_goal="custom", video_codecs=_PREFER_H264)
    )
    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column(
            "auto_subtitles", sa.String(16), server_default="fallback", nullable=False,
            comment="YouTube's auto-generated subtitles: never, fallback (when there is no real one) or always",
        ))


def downgrade() -> None:
    with op.batch_alter_table("download_profiles") as batch:
        batch.drop_column("auto_subtitles")
    with op.batch_alter_table("local_media_profiles") as batch:
        for column in (
            "audio_language", "audio_format", "audio_codec", "container", "codec_fallback",
            "video_codecs", "quality_goal", "subtitle_language_mode", "subtitle_languages",
        ):
            batch.drop_column(column)
