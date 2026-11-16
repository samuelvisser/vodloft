"""Give Local Media Profiles their own filename mode, file dates and NFO options.

Revision ID: ee6dab087875
Revises: bb0e7c5e17cc
Create Date: 2026-11-16

Every Local Media Profile gets the filename mode that was a system setting, a choice to give files
their publish date, and a choice for NFO files Kodi can read. Collection Local Media Profiles can
also write show and season NFO files. The filename mode starts as Windows-compatible; a background
migration gives existing profiles the mode their Settings had, as config.yml is outside the database.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "ee6dab087875"
down_revision = "bb0e7c5e17cc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column(
            "kodi_safe_nfo", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="NFO files replace the characters Kodi cannot show, such as emoji",
        ))
        batch.add_column(sa.Column(
            "filename_restriction_mode", sa.String(16), nullable=False, server_default="windows",
            comment="How file and folder names are made safe: unrestricted, windows or restricted (ASCII only)",
        ))
        batch.add_column(sa.Column(
            "file_date_from_publish_date", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="Downloaded files get the date the media was published, so players sort them by air date",
        ))
    with op.batch_alter_table("local_media_profiles_collection") as batch:
        batch.add_column(sa.Column(
            "show_nfo", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="Write tvshow.nfo in the collection's folder and season.nfo in each season's folder",
        ))


def downgrade() -> None:
    with op.batch_alter_table("local_media_profiles_collection") as batch:
        batch.drop_column("show_nfo")
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("file_date_from_publish_date")
        batch.drop_column("filename_restriction_mode")
        batch.drop_column("kodi_safe_nfo")
