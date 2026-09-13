"""Initial VodLoft schema.

Revision ID: 0001_vodloft
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_vodloft"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False, unique=True),
        sa.Column("extractor", sa.String(length=128), nullable=False),
        sa.Column("extractor_id", sa.String(length=512), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("uploader", sa.Text(), nullable=True),
        sa.Column("uploader_id", sa.Text(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("channel_id", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("extractor", "extractor_id", name="uq_collection_extractor_id"),
    )
    op.create_index("ix_collections_kind", "collections", ["kind"])
    op.create_index("ix_collections_extractor", "collections", ["extractor"])

    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_url", sa.Text(), nullable=False, unique=True),
        sa.Column("extractor", sa.String(length=128), nullable=False),
        sa.Column("extractor_id", sa.String(length=512), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("uploader", sa.Text(), nullable=True),
        sa.Column("uploader_id", sa.Text(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("channel_id", sa.Text(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("upload_date", sa.Date(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("downloaded_path", sa.Text(), nullable=True),
        sa.Column("downloaded_format", sa.String(length=128), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("extractor", "extractor_id", name="uq_video_extractor_id"),
    )
    op.create_index("ix_videos_extractor", "videos", ["extractor"])

    op.create_table(
        "collection_videos",
        sa.Column("collection_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "local_media_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True),
        sa.Column("media_kind", sa.String(length=16), nullable=False),
        sa.Column("output_template", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "download_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True),
        sa.Column("local_media_profile_id", sa.Integer(), sa.ForeignKey("local_media_profiles.id"), nullable=False),
        sa.Column("format_selector", sa.Text(), nullable=False),
        sa.Column("merge_output_format", sa.String(length=32), nullable=True),
        sa.Column("audio_format", sa.String(length=32), nullable=True),
        sa.Column("write_subtitles", sa.Boolean(), nullable=False),
        sa.Column("embed_metadata", sa.Boolean(), nullable=False),
        sa.Column("embed_thumbnail", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "stream_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True),
        sa.Column("format_selector", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("stream_profiles")
    op.drop_table("download_profiles")
    op.drop_table("local_media_profiles")
    op.drop_table("collection_videos")
    op.drop_index("ix_videos_extractor", table_name="videos")
    op.drop_table("videos")
    op.drop_index("ix_collections_extractor", table_name="collections")
    op.drop_index("ix_collections_kind", table_name="collections")
    op.drop_table("collections")
