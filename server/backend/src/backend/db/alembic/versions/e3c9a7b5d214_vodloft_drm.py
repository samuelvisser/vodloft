"""Mark media that is protected by DRM, so VODLoft stops trying to download it.

Revision ID: e3c9a7b5d214
Revises: b5d2e8a4c716
Create Date: 2026-10-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e3c9a7b5d214"
down_revision = "b5d2e8a4c716"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(sa.Column(
            "drm_protected", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="The media is protected by DRM and cannot be downloaded",
        ))


def downgrade() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("drm_protected")
