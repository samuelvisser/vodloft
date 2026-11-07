"""Describe what the picture columns hold.

A picture column holds either the web address of an image at its Source, or the path of an image
VODLoft made itself and keeps in its thumbnail folder.

Revision ID: 8124198d716f
Revises: db11a36f288f
Create Date: 2026-11-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "8124198d716f"
down_revision = "db11a36f288f"
branch_labels = None
depends_on = None

_COMMENT = (
    "A picture: the web address of an image at its Source, "
    "or thumbnails/<name>.jpg for an image VODLoft made itself and keeps in its thumbnail folder"
)
_TABLES = ("collections", "media_items_episode", "media_items_movie", "media_items_video", "movie_extra_sources")
_COLUMNS = ("background_image_path", "thumbnail_landscape_path", "thumbnail_portrait_path", "thumbnail_square_path")


def _set_comment(comment: str | None) -> None:
    # SQLite keeps no column comments, and changing one there would rebuild every table.
    if op.get_bind().dialect.name == "sqlite":
        return
    for table in _TABLES:
        for column in _COLUMNS:
            op.alter_column(table, column, existing_type=sa.String(), existing_nullable=True, comment=comment)


def upgrade() -> None:
    _set_comment(_COMMENT)


def downgrade() -> None:
    _set_comment(None)
