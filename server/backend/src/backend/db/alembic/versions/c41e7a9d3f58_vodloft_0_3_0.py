"""Upgrade the VODLoft 0.2.0 schema to 0.3.0.

The single release migration for 0.3.0 (0.3.1 changed no schema). It marks
media that its Source only gives to a paying account, such as NPO Plus.

Revision ID: c41e7a9d3f58
Revises: a7e4c2d91b35
Create Date: 2026-10-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c41e7a9d3f58"
down_revision = "a7e4c2d91b35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(sa.Column(
            "needs_subscription", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="The Source only gives the media to a paying account, such as NPO Plus",
        ))


def downgrade() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("needs_subscription")
