"""WebDAV shares can list the extras of an episode beside it.

Revision ID: 12c4ec47817e
Revises: fbd592943ccc
Create Date: 2026-11-18

Existing shares keep listing them in the show's Trailers and Other folders.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "12c4ec47817e"
down_revision = "fbd592943ccc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stream_profiles_webdav",
        sa.Column(
            "episode_extras", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="List the extras of an episode beside it, named after its file; otherwise in the show's Trailers and Other folders",
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("stream_profiles_webdav") as batch:
        batch.drop_column("episode_extras")
