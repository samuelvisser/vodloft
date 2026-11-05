"""RSS feeds can proxy a Site's video, and stream YouTube at 360p, 720p and 1080p only.

RSS stream profiles get ``proxy_source_stream``, off. Profiles of YouTube collections that stream
from YouTube move to the nearest of the resolutions it streams: 480p to 720p, 1440p and higher to
1080p.

Revision ID: 53adf1f1b502
Revises: 688634d39f23
Create Date: 2026-11-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "53adf1f1b502"
down_revision = "688634d39f23"
branch_labels = None
depends_on = None

_FORMATS = {
    "format_480p": "format_720p",
    "format_1440p": "format_1080p",
    "format_4k": "format_1080p",
    "format_8k": "format_1080p",
}


def upgrade() -> None:
    with op.batch_alter_table("stream_profiles_rss") as batch:
        batch.add_column(sa.Column("proxy_source_stream", sa.Boolean(), nullable=False, server_default="0"))

    bind = op.get_bind()
    for old, new in _FORMATS.items():
        bind.execute(sa.text(
            "UPDATE stream_profiles SET preferred_format = :new WHERE preferred_format = :old "
            "AND use_source_stream = :streams AND collection_id IN ("
            "SELECT id FROM collections WHERE source_key = 'ytdlp' AND ("
            "sharing_url LIKE '%youtube.com/%' OR sharing_url LIKE '%youtu.be/%'))"
        ), {"old": old, "new": new, "streams": True})


def downgrade() -> None:
    with op.batch_alter_table("stream_profiles_rss") as batch:
        batch.drop_column("proxy_source_stream")
