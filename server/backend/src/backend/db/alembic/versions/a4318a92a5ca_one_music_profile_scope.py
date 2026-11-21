"""Collection profiles for Music tracks and for Music videos become profiles for Music.

A profile for Music keeps tracks when it downloads audio only, and music videos when it downloads video, so what it is
available for no longer says which of the two it keeps.

Revision ID: a4318a92a5ca
Revises: 7c41e2a9d5b3
Create Date: 2026-11-21
"""
from __future__ import annotations

from alembic import op


revision = "a4318a92a5ca"
down_revision = "7c41e2a9d5b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE local_media_profiles_collection SET collection_scope = 'music' "
        "WHERE collection_scope IN ('music_tracks', 'music_videos')"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE local_media_profiles_collection SET collection_scope = 'music_tracks' "
        "WHERE collection_scope = 'music' AND id IN ("
        "SELECT id FROM local_media_profiles WHERE preferred_format = 'format_audio_only')"
    )
    op.execute(
        "UPDATE local_media_profiles_collection SET collection_scope = 'music_videos' WHERE collection_scope = 'music'"
    )
