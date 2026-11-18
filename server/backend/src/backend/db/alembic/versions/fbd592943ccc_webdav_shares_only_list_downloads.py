"""WebDAV shares only list downloads.

Revision ID: fbd592943ccc
Revises: 940039d2712d
Create Date: 2026-11-18

A WebDAV share no longer streams episodes straight from their Site, so every WebDAV stream profile now
uses downloads and never the Site's stream.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "fbd592943ccc"
down_revision = "940039d2712d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    stream_profiles = sa.table(
        "stream_profiles",
        sa.column("type", sa.String),
        sa.column("use_downloads", sa.Boolean),
        sa.column("use_source_stream", sa.Boolean),
    )
    op.execute(
        stream_profiles.update()
        .where(stream_profiles.c.type == "webdav")
        .values(use_downloads=True, use_source_stream=False)
    )


def downgrade() -> None:
    # Which shares streamed from their Site before is not kept; they stay downloads only.
    pass
