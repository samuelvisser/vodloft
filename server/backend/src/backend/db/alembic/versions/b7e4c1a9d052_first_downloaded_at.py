"""When each download first had a file, kept when the file is downloaded again.

Revision ID: b7e4c1a9d052
Revises: 7b3c683c941f
Create Date: 2026-11-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7e4c1a9d052"
down_revision = "7b3c683c941f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_downloads", sa.Column(
        "first_downloaded_at", sa.DateTime(timezone=True), nullable=True,
        comment="When this download first had a file; unlike downloaded_at, a new download keeps it",
    ))
    # The earliest completed attempt in the download's history, or its latest download when that is earlier
    # (an adopted file's own time) or the history has none.
    op.execute(sa.text("""
        UPDATE media_downloads SET first_downloaded_at = (
            SELECT MIN(h.occurred_at) FROM media_download_history h
            WHERE h.media_download_id = media_downloads.id AND h.action = 'completed'
        )
    """))
    op.execute(sa.text("""
        UPDATE media_downloads SET first_downloaded_at = downloaded_at
        WHERE downloaded_at IS NOT NULL
          AND (first_downloaded_at IS NULL OR downloaded_at < first_downloaded_at)
    """))


def downgrade() -> None:
    with op.batch_alter_table("media_downloads") as batch:
        batch.drop_column("first_downloaded_at")
