"""Remember quick downloads in a history: what, from where, as what, and how each one ended.

Revision ID: b93d5e7a1c42
Revises: c41e7a9d3f58
Create Date: 2026-10-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b93d5e7a1c42"
down_revision = "c41e7a9d3f58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quick_download_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("quick_download_id", sa.String(), nullable=False, comment="Id of the quick download's ready folder"),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False, comment="Id of the Source, as registered in sources"),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("format", sa.String(), nullable=False, comment="The choice as people read it, such as 'Video · 1080p MP4'"),
        sa.Column("choice", sa.JSON(), nullable=False, comment="The choice, to download it again the same way"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "outcome", sa.String(), nullable=False,
            comment="working, ready, downloaded, expired, discarded, canceled, failed or refused",
        ),
        sa.Column("message", sa.String(), nullable=True, comment="Why it failed or was refused"),
        sa.Column("owner", sa.String(), nullable=True, comment="The user who asked for it, once VODLoft has users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quick_download_history")),
        sa.UniqueConstraint("quick_download_id", name=op.f("uq_quick_download_history_quick_download_id")),
    )
    op.create_index("ix_quick_download_history_started_at", "quick_download_history", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_quick_download_history_started_at", table_name="quick_download_history")
    op.drop_table("quick_download_history")
