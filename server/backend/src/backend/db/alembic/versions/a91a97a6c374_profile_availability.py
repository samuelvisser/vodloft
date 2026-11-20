"""Music and Video profiles say what they are available for.

A Music profile becomes a Collection profile available for Music tracks, and a Collection profile for a Music
collection's videos one available for Music videos. A Video profile gets what it is available for: videos, movies or
both. The two profiles every installation starts with keep what they were made for, unless they already hold
downloads of the other kind.

Revision ID: a91a97a6c374
Revises: ad2922b7ff06
Create Date: 2026-11-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "a91a97a6c374"
down_revision = "ad2922b7ff06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "local_media_profiles_video",
        sa.Column(
            "video_scope", sa.String(16), nullable=False, server_default="both",
            comment="What the profile is offered for: videos, movies or both",
        ),
    )
    op.execute(
        "UPDATE local_media_profiles_video SET video_scope = 'movies' "
        "WHERE id IN (SELECT id FROM local_media_profiles WHERE slug = 'vodloft-movies') "
        "AND id NOT IN (SELECT local_media_profile_id FROM media_downloads WHERE type = 'video' AND local_media_profile_id IS NOT NULL)"
    )
    op.execute(
        "UPDATE local_media_profiles_video SET video_scope = 'videos' "
        "WHERE id IN (SELECT id FROM local_media_profiles WHERE slug = 'vodloft-videos') "
        "AND id NOT IN (SELECT local_media_profile_id FROM media_downloads "
        "WHERE type IN ('movie', 'movie_extra') AND local_media_profile_id IS NOT NULL)"
    )
    op.execute(
        "UPDATE local_media_profiles_collection SET collection_scope = 'music_tracks' "
        "WHERE id IN (SELECT id FROM local_media_profiles WHERE type = 'music')"
    )
    op.execute(
        "UPDATE local_media_profiles_collection SET collection_scope = 'music_videos' WHERE collection_scope = 'music'"
    )
    op.execute("UPDATE local_media_profiles SET type = 'collection' WHERE type = 'music'")


def downgrade() -> None:
    op.execute(
        "UPDATE local_media_profiles SET type = 'music' "
        "WHERE id IN (SELECT id FROM local_media_profiles_collection WHERE collection_scope = 'music_tracks')"
    )
    op.execute(
        "UPDATE local_media_profiles_collection SET collection_scope = 'music' "
        "WHERE collection_scope IN ('music_tracks', 'music_videos')"
    )
    with op.batch_alter_table("local_media_profiles_video") as batch:
        batch.drop_column("video_scope")
