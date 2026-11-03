"""Your own yt-dlp options move from Local Media Profiles to the yt-dlp Source.

A Local Media Profile is used by Collections of every Source, so options that
only yt-dlp understands now live on the yt-dlp Source in Settings, where they
always apply. The options of every Local Media Profile are kept there, each
distinct text once.

Revision ID: a93c6e0d1f27
Revises: e2f7a41c9d05
Create Date: 2026-11-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "a93c6e0d1f27"
down_revision = "e2f7a41c9d05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch:
        batch.add_column(sa.Column(
            "ytdlp_options", sa.Text(), server_default="", nullable=False,
            comment="Your own yt-dlp options for every download of the yt-dlp Source, one or more per line",
        ))
    connection = op.get_bind()
    texts: list[str] = []
    for (text,) in connection.execute(sa.text(
        "SELECT ytdlp_options FROM local_media_profiles WHERE ytdlp_options != '' ORDER BY id"
    )):
        if text.strip() and text not in texts:
            texts.append(text)
    if texts:
        merged = "\n".join(texts)
        if connection.execute(sa.text("SELECT COUNT(*) FROM settings")).scalar_one():
            connection.execute(sa.text("UPDATE settings SET ytdlp_options = :text"), {"text": merged})
        else:
            connection.execute(sa.text("INSERT INTO settings (ytdlp_options) VALUES (:text)"), {"text": merged})
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("ytdlp_options")


def downgrade() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column(
            "ytdlp_options", sa.Text(), server_default="", nullable=False,
            comment="Your own yt-dlp options, one or more per line, for downloads yt-dlp makes",
        ))
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("ytdlp_options")
