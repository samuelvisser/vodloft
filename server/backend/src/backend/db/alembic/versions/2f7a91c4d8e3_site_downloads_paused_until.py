"""Remember until when a Site's automatic downloads wait after it throttled a download.

Revision ID: 2f7a91c4d8e3
Revises: 6cc8e0f91b00
Create Date: 2026-11-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "2f7a91c4d8e3"
down_revision = "6cc8e0f91b00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sites", sa.Column(
        "downloads_paused_until", sa.DateTime(timezone=True), nullable=True,
        comment="Automatic downloads from the Site wait until then, because it throttled a download",
    ))


def downgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.drop_column("downloads_paused_until")
