"""A WebDAV stream profile's title is its folder name.

Revision ID: 940039d2712d
Revises: 2f7a91c4d8e3
Create Date: 2026-11-18

WebDAV stream profiles had a folder name beside their title, which only stood in for the title when it
was empty. The title now names the show's folder, so a folder name that was set becomes the title, and
the column goes.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "940039d2712d"
down_revision = "2f7a91c4d8e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A title that is the collection's own is stored as nothing, as the API stores it.
    op.execute(sa.text(
        "UPDATE stream_profiles SET overwrite_collection_title = ("
        " SELECT CASE WHEN w.folder_name = c.title THEN NULL ELSE w.folder_name END"
        " FROM stream_profiles_webdav w JOIN collections c ON c.id = stream_profiles.collection_id"
        " WHERE w.id = stream_profiles.id"
        ") WHERE id IN (SELECT id FROM stream_profiles_webdav WHERE folder_name IS NOT NULL)"
    ))
    with op.batch_alter_table("stream_profiles_webdav") as batch:
        batch.drop_column("folder_name")


def downgrade() -> None:
    # An empty folder name used the title, so every share keeps its folder.
    with op.batch_alter_table("stream_profiles_webdav") as batch:
        batch.add_column(sa.Column(
            "folder_name", sa.String(), nullable=True, comment="The show's folder; empty uses the profile's title",
        ))
