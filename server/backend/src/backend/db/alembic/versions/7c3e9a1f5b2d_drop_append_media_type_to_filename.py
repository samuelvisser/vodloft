"""Local Media Profiles no longer keep append_media_type_to_filename.

Templates say in Jinja whether a movie extra's file name ends in its media type, and
nothing read the column any more.

Revision ID: 7c3e9a1f5b2d
Revises: db11a36f288f
Create Date: 2026-11-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7c3e9a1f5b2d"
down_revision = "db11a36f288f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("append_media_type_to_filename")


def downgrade() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column(
            "append_media_type_to_filename", sa.Boolean(), server_default="0", nullable=False,
        ))
