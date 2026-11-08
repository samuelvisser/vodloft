"""Index the columns that find a profile's downloads and a collection's stream profiles.

In a large library the profile tables and the download worker look these up for every profile, and
without an index each lookup reads the whole table.

Revision ID: 5b8e1f3c2a90
Revises: 8124198d716f
Create Date: 2026-11-08
"""
from __future__ import annotations

from alembic import op

revision = "5b8e1f3c2a90"
down_revision = "8124198d716f"
branch_labels = None
depends_on = None

_INDEXES = (
    ("ix_media_downloads_episode_download_profile_id", "media_downloads_episode", "download_profile_id"),
    ("ix_stream_profiles_collection_id", "stream_profiles", "collection_id"),
    ("ix_download_profiles_local_media_profile_id", "download_profiles", "local_media_profile_id"),
)


def upgrade() -> None:
    for name, table, column in _INDEXES:
        op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _column in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
