"""RSS feeds only serve HLS video from Sites that stream it or download it as an HLS bundle.

Feeds of other Sites, such as NPO Start and every yt-dlp Site but YouTube, move from their HLS video
output to the MP4 one that takes its place: audio_hls to audio_mp4, mp4_hls to mp4.

Revision ID: aa950d2ab545
Revises: 53adf1f1b502
Create Date: 2026-11-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "aa950d2ab545"
down_revision = "53adf1f1b502"
branch_labels = None
depends_on = None

_MODES = {"audio_hls": "audio_mp4", "mp4_hls": "mp4"}


def upgrade() -> None:
    bind = op.get_bind()
    for old, new in _MODES.items():
        bind.execute(sa.text(
            "UPDATE stream_profiles_rss SET video_output_mode = :new WHERE video_output_mode = :old "
            "AND id IN (SELECT stream_profiles.id FROM stream_profiles JOIN collections "
            "ON collections.id = stream_profiles.collection_id "
            "WHERE collections.source_key != 'dailywire' AND NOT (collections.source_key = 'ytdlp' AND ("
            "collections.sharing_url LIKE '%youtube.com/%' OR collections.sharing_url LIKE '%youtu.be/%')))"
        ), {"old": old, "new": new})


def downgrade() -> None:
    # The MP4 outputs keep working, so the feeds stay as they are.
    pass
