"""Add videos: single videos added on their own, with their downloads and Local Media Profiles.

Revision ID: b5d2e8a4c716
Revises: a3e7c1d9f052
Create Date: 2026-10-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from backend.db.datetime_types import UTCDateTime


revision = "b5d2e8a4c716"
down_revision = "a3e7c1d9f052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_items_video",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("sharing_url", sa.String(), nullable=False),
        sa.Column("author_name", sa.String(), nullable=True),
        sa.Column("author_url", sa.String(), nullable=True),
        sa.Column("published_at", UTCDateTime(), nullable=True),
        sa.Column("title", sa.String(), nullable=False, server_default=""),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=False, server_default="0"),
        sa.Column("background_image_path", sa.String(), nullable=True),
        sa.Column("thumbnail_landscape_path", sa.String(), nullable=True),
        sa.Column("thumbnail_portrait_path", sa.String(), nullable=True),
        sa.Column("thumbnail_square_path", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["id"], ["media_items.id"],
            name=op.f("fk_media_items_video_id_media_items"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_items_video")),
    )
    op.create_index(op.f("ix_media_items_video_slug"), "media_items_video", ["slug"])

    op.create_table(
        "media_downloads_video",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["id"], ["media_downloads.id"],
            name=op.f("fk_media_downloads_video_id_media_downloads"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_downloads_video")),
    )

    op.create_table(
        "local_media_profiles_video",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["id"], ["local_media_profiles.id"],
            name=op.f("fk_local_media_profiles_video_id_local_media_profiles"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_local_media_profiles_video")),
    )




def downgrade() -> None:
    bind = op.get_bind()
    # Remove the parent rows first so nothing points at a type that no longer exists.
    bind.execute(sa.text("DELETE FROM media_downloads WHERE type = 'video'"))
    bind.execute(sa.text("DELETE FROM media_items WHERE type = 'video'"))
    bind.execute(sa.text("DELETE FROM local_media_profiles WHERE type = 'video'"))
    op.drop_table("local_media_profiles_video")
    op.drop_table("media_downloads_video")
    op.drop_index(op.f("ix_media_items_video_slug"), table_name="media_items_video")
    op.drop_table("media_items_video")
