"""Preserve previous Source metadata for a scoped repair.

Revision ID: e93a4f61b2d0
Revises: d82b1c44a901
"""
from alembic import op
import sqlalchemy as sa

revision = "e93a4f61b2d0"
down_revision = "d82b1c44a901"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("vodloft_source_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String, nullable=False),
        sa.Column("connection_id", sa.Integer, nullable=True),
        sa.Column("runtime_version", sa.String, nullable=False),
        sa.Column("metadata_snapshot", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_vodloft_source_snapshots_item", "vodloft_source_snapshots", ["item_id", "id"])


def downgrade():
    op.drop_index("ix_vodloft_source_snapshots_item", table_name="vodloft_source_snapshots")
    op.drop_table("vodloft_source_snapshots")
