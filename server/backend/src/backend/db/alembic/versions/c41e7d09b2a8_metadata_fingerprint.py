"""Fingerprints of the metadata VODLoft last wrote completely to a downloaded file: its tags and its NFO, so that
rewriting metadata only writes what changes. Files downloaded before them have none, and are written once.

Revision ID: c41e7d09b2a8
Revises: aa8710c37ebc
Create Date: 2026-11-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c41e7d09b2a8"
down_revision = "aa8710c37ebc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_downloads", sa.Column(
        "tags_fingerprint", sa.String(length=64), nullable=True,
        comment='The fingerprint of the tags VODLoft last embedded in the file, "none" when it embedded none; None when unknown',
    ))
    op.add_column("media_downloads", sa.Column(
        "nfo_fingerprint", sa.String(length=64), nullable=True,
        comment='The fingerprint of the NFO VODLoft last wrote beside the file, "none" when it wrote none; None when unknown',
    ))


def downgrade() -> None:
    with op.batch_alter_table("media_downloads") as batch:
        batch.drop_column("nfo_fingerprint")
        batch.drop_column("tags_fingerprint")
