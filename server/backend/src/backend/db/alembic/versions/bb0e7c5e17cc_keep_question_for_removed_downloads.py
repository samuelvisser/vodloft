"""Ask whether to keep a download whose episode the Source no longer has.

A download remembers when the person answered that question, so the Home page stops asking and
retention may delete it again when they chose not to keep it.

Revision ID: bb0e7c5e17cc
Revises: 3f9c1e7a5b24
Create Date: 2026-11-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "bb0e7c5e17cc"
down_revision = "3f9c1e7a5b24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_downloads_episode") as batch:
        batch.add_column(sa.Column(
            "removal_answered_at", sa.DateTime(), nullable=True,
            comment="When the person answered whether to keep it after its episode left the Source",
        ))


def downgrade() -> None:
    with op.batch_alter_table("media_downloads_episode") as batch:
        batch.drop_column("removal_answered_at")
