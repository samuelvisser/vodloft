"""Align profiles and download artifacts with WireLoft's ownership model.

Revision ID: 0003_profile_alignment
Revises: 0002_standalone_defaults
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0003_profile_alignment"
down_revision = "0002_standalone_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The first scaffold used global download/stream presets. WireLoft scopes
    # those profiles to a show; VodLoft scopes them to a collection instead.
    op.execute(sa.text("DELETE FROM download_profiles WHERE name = 'Best quality'"))
    op.execute(sa.text("DELETE FROM stream_profiles WHERE name = 'Browser compatible'"))

    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column("slug", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("scope", sa.String(length=16), nullable=False, server_default="video"))
        batch.add_column(sa.Column("preferred_format", sa.Text(), nullable=False, server_default="bestvideo*+bestaudio/best"))
        batch.add_column(sa.Column("merge_output_format", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("audio_format", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("write_subtitles", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("embed_metadata", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("embed_thumbnail", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_index("ix_local_media_profiles_slug", ["slug"], unique=True)
        batch.create_index("ix_local_media_profiles_scope", ["scope"], unique=False)

    op.execute(sa.text("UPDATE local_media_profiles SET slug = 'default-video' WHERE name = 'Default video'"))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    op.bulk_insert(
        sa.table(
            "local_media_profiles",
            sa.column("slug", sa.String()),
            sa.column("name", sa.String()),
            sa.column("scope", sa.String()),
            sa.column("media_kind", sa.String()),
            sa.column("output_template", sa.Text()),
            sa.column("preferred_format", sa.Text()),
            sa.column("merge_output_format", sa.String()),
            sa.column("audio_format", sa.String()),
            sa.column("write_subtitles", sa.Boolean()),
            sa.column("embed_metadata", sa.Boolean()),
            sa.column("embed_thumbnail", sa.Boolean()),
            sa.column("created_at", sa.DateTime()),
            sa.column("updated_at", sa.DateTime()),
        ),
        [{
            "slug": "default-collection-video",
            "name": "Default collection video",
            "scope": "collection",
            "media_kind": "video",
            "output_template": "/downloads/%(channel,uploader)s/%(title)s [%(id)s].%(ext)s",
            "preferred_format": "bestvideo*+bestaudio/best",
            "merge_output_format": None,
            "audio_format": None,
            "write_subtitles": False,
            "embed_metadata": True,
            "embed_thumbnail": False,
            "created_at": now,
            "updated_at": now,
        }],
    )

    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column("collection_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("enable_profile", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.create_foreign_key(
            "fk_download_profiles_collection_id_collections",
            "collections",
            ["collection_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_download_profiles_collection_id", ["collection_id"], unique=False)
        batch.create_unique_constraint(
            "uq_download_profile_collection_media",
            ["collection_id", "local_media_profile_id"],
        )
        batch.drop_column("format_selector")
        batch.drop_column("merge_output_format")
        batch.drop_column("audio_format")
        batch.drop_column("write_subtitles")
        batch.drop_column("embed_metadata")
        batch.drop_column("embed_thumbnail")

    with op.batch_alter_table("stream_profiles") as batch:
        batch.add_column(sa.Column("collection_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("enable_profile", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("use_downloads", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key(
            "fk_stream_profiles_collection_id_collections",
            "collections",
            ["collection_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_stream_profiles_collection_id", ["collection_id"], unique=False)

    op.create_table(
        "media_downloads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("local_media_profile_id", sa.Integer(), sa.ForeignKey("local_media_profiles.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("downloaded_bytes", sa.Integer(), nullable=True),
        sa.Column("format_downloaded", sa.String(length=128), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("video_id", "local_media_profile_id", name="uq_media_download_video_profile"),
    )
    op.create_index("ix_media_downloads_video_id", "media_downloads", ["video_id"])
    op.create_index("ix_media_downloads_local_media_profile_id", "media_downloads", ["local_media_profile_id"])
    op.create_index("ix_media_downloads_status", "media_downloads", ["status"])


def downgrade() -> None:
    op.drop_index("ix_media_downloads_status", table_name="media_downloads")
    op.drop_index("ix_media_downloads_local_media_profile_id", table_name="media_downloads")
    op.drop_index("ix_media_downloads_video_id", table_name="media_downloads")
    op.drop_table("media_downloads")

    with op.batch_alter_table("stream_profiles") as batch:
        batch.drop_index("ix_stream_profiles_collection_id")
        batch.drop_constraint("fk_stream_profiles_collection_id_collections", type_="foreignkey")
        batch.drop_column("use_downloads")
        batch.drop_column("enable_profile")
        batch.drop_column("collection_id")

    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column("format_selector", sa.Text(), nullable=False, server_default="bestvideo*+bestaudio/best"))
        batch.add_column(sa.Column("merge_output_format", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("audio_format", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("write_subtitles", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("embed_metadata", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("embed_thumbnail", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.drop_constraint("uq_download_profile_collection_media", type_="unique")
        batch.drop_index("ix_download_profiles_collection_id")
        batch.drop_constraint("fk_download_profiles_collection_id_collections", type_="foreignkey")
        batch.drop_column("enable_profile")
        batch.drop_column("collection_id")

    op.execute(sa.text("DELETE FROM local_media_profiles WHERE slug = 'default-collection-video'"))
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_index("ix_local_media_profiles_scope")
        batch.drop_index("ix_local_media_profiles_slug")
        batch.drop_column("embed_thumbnail")
        batch.drop_column("embed_metadata")
        batch.drop_column("write_subtitles")
        batch.drop_column("audio_format")
        batch.drop_column("merge_output_format")
        batch.drop_column("preferred_format")
        batch.drop_column("scope")
        batch.drop_column("slug")
