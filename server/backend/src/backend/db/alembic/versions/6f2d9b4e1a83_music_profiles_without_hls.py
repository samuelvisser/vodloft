"""Profiles for Music that keep an HLS bundle download plain video up to 1080p instead.

An HLS bundle lets podcast apps switch resolutions. A profile for Music keeps tracks or music videos, which media
servers play as plain video, and an HLS bundle went up to 1080p.

Revision ID: 6f2d9b4e1a83
Revises: a4318a92a5ca
Create Date: 2026-11-21
"""
from __future__ import annotations

from alembic import op


revision = "6f2d9b4e1a83"
down_revision = "a4318a92a5ca"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE local_media_profiles SET preferred_format = 'format_1080p' "
        "WHERE preferred_format = 'format_hls' AND id IN ("
        "SELECT id FROM local_media_profiles_collection WHERE collection_scope = 'music')"
    )


def downgrade() -> None:
    pass
