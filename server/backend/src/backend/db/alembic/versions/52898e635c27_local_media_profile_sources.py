"""Local Media Profiles offered for only some Sources.

Revision ID: 52898e635c27
Revises: c5e9a2f17b30
Create Date: 2026-11-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "52898e635c27"
down_revision = "c5e9a2f17b30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(
            sa.Column(
                "source_keys", sa.JSON(), nullable=True,
                comment="The Sources this profile is offered for; NULL offers it for every Source",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("source_keys")
