"""Remember how often and when each creator's page is opened

The Library's Often used and Recently used orders count a creator's own page beside its collections' pages.

Revision ID: 7c4d2e9a1b36
Revises: 684e98f029ec
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7c4d2e9a1b36"
down_revision = "684e98f029ec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("creators", sa.Column(
        "open_count", sa.Integer(), nullable=False, server_default="0",
        comment="How often the creator's page was opened",
    ))
    op.add_column("creators", sa.Column(
        "last_opened_at", sa.DateTime(timezone=True), nullable=True,
        comment="When the creator's page was last opened",
    ))


def downgrade() -> None:
    with op.batch_alter_table("creators") as batch:
        batch.drop_column("last_opened_at")
        batch.drop_column("open_count")
