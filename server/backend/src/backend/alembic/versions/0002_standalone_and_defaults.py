"""Track standalone videos and create usable default profiles.

Revision ID: 0002_standalone_defaults
Revises: 0001_vodloft
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0002_standalone_defaults"
down_revision = "0001_vodloft"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("standalone", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_videos_standalone", "videos", ["standalone"])

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    op.bulk_insert(
        sa.table(
            "local_media_profiles",
            sa.column("id", sa.Integer()),
            sa.column("name", sa.String()),
            sa.column("media_kind", sa.String()),
            sa.column("output_template", sa.Text()),
            sa.column("created_at", sa.DateTime()),
            sa.column("updated_at", sa.DateTime()),
        ),
        [{
            "id": 1,
            "name": "Default video",
            "media_kind": "video",
            "output_template": "/downloads/%(uploader)s/%(title)s [%(id)s].%(ext)s",
            "created_at": now,
            "updated_at": now,
        }],
    )
    op.bulk_insert(
        sa.table(
            "download_profiles",
            sa.column("id", sa.Integer()),
            sa.column("name", sa.String()),
            sa.column("local_media_profile_id", sa.Integer()),
            sa.column("format_selector", sa.Text()),
            sa.column("merge_output_format", sa.String()),
            sa.column("audio_format", sa.String()),
            sa.column("write_subtitles", sa.Boolean()),
            sa.column("embed_metadata", sa.Boolean()),
            sa.column("embed_thumbnail", sa.Boolean()),
            sa.column("created_at", sa.DateTime()),
            sa.column("updated_at", sa.DateTime()),
        ),
        [{
            "id": 1,
            "name": "Best quality",
            "local_media_profile_id": 1,
            "format_selector": "bestvideo*+bestaudio/best",
            "merge_output_format": None,
            "audio_format": None,
            "write_subtitles": False,
            "embed_metadata": True,
            "embed_thumbnail": False,
            "created_at": now,
            "updated_at": now,
        }],
    )
    op.bulk_insert(
        sa.table(
            "stream_profiles",
            sa.column("id", sa.Integer()),
            sa.column("name", sa.String()),
            sa.column("format_selector", sa.Text()),
            sa.column("created_at", sa.DateTime()),
            sa.column("updated_at", sa.DateTime()),
        ),
        [{
            "id": 1,
            "name": "Browser compatible",
            "format_selector": "best[protocol^=http][vcodec!=none][acodec!=none]/best",
            "created_at": now,
            "updated_at": now,
        }],
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM stream_profiles WHERE id = 1 AND name = 'Browser compatible'"))
    op.execute(sa.text("DELETE FROM download_profiles WHERE id = 1 AND name = 'Best quality'"))
    op.execute(sa.text("DELETE FROM local_media_profiles WHERE id = 1 AND name = 'Default video'"))
    op.drop_index("ix_videos_standalone", table_name="videos")
    op.drop_column("videos", "standalone")
