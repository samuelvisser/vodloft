"""Give imported files to the Download Profile of their Collection and Local Media Profile.

Files taken in by an importer or by matching existing files were recorded without a Download Profile.
The profile only claimed them once it wanted their episode again, so a file whose episode was already
outside the profile's date line was never deleted by its retention. Every such download now belongs to
the Collection's Download Profile for its Local Media Profile, like a file the profile downloaded itself.

Revision ID: a0eceaa70db5
Revises: 8124198d716f
Create Date: 2026-11-08
"""
from __future__ import annotations

from alembic import op

revision = "a0eceaa70db5"
down_revision = "8124198d716f"
branch_labels = None
depends_on = None

_PROFILE = """
    SELECT download_profiles.id
    FROM download_profiles
    JOIN media_downloads ON media_downloads.id = media_downloads_episode.id
    JOIN media_items_episode ON media_items_episode.id = media_downloads.media_item_id
    WHERE download_profiles.collection_id = media_items_episode.collection_id
      AND download_profiles.local_media_profile_id = media_downloads.local_media_profile_id
"""


def upgrade() -> None:
    op.execute(f"""
        UPDATE media_downloads_episode
        SET download_profile_id = ({_PROFILE})
        WHERE download_profile_id IS NULL
          AND EXISTS (
              SELECT 1 FROM media_download_history
              WHERE media_download_history.media_download_id = media_downloads_episode.id
                AND media_download_history.action = 'imported'
          )
          AND EXISTS ({_PROFILE})
    """)


def downgrade() -> None:
    # Which downloads had no Download Profile before is not kept; they stay with their profile.
    pass
