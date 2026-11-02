"""The Daily Wire's episodes are uploaded by their show's host.

Revision ID: b918e345f620
Revises: d0f28c7f863e
Create Date: 2026-11-02

The Daily Wire names no uploader per episode, so new episodes take their show's
author. This fills it in for the episodes VODLoft already has.
"""
from __future__ import annotations

from alembic import op


revision = "b918e345f620"
down_revision = "d0f28c7f863e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE media_items_episode
        SET author_name = (
            SELECT NULLIF(collections.author_name, '') FROM collections
            WHERE collections.id = media_items_episode.collection_id
        )
        WHERE author_name IS NULL
          AND id IN (SELECT id FROM media_items WHERE source_key = 'dailywire')
        """
    )


def downgrade() -> None:
    pass
