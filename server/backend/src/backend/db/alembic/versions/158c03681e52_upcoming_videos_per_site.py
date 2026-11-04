"""Each Site chooses whether VODLoft adds its upcoming and live videos.

Revision ID: 158c03681e52
Revises: b9dbb772c34e
Create Date: 2026-11-04

VODLoft can add a video that is upcoming or live and follow it until it is
published. Every Site does so unless the user turns it off.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "158c03681e52"
down_revision = "b9dbb772c34e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.add_column(sa.Column(
            "pending_checks", sa.Boolean(), nullable=False, server_default="1",
            comment="Whether upcoming and live videos are added and followed until they are published",
        ))


def downgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.drop_column("pending_checks")
