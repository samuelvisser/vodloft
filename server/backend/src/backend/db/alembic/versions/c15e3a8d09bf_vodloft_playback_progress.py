"""Persist local playback position for the authenticated administrator.

Revision ID: c15e3a8d09bf
Revises: b13c80e9a7d4
"""
from alembic import op
import sqlalchemy as sa

revision = "c15e3a8d09bf"
down_revision = "b13c80e9a7d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("vodloft_playback_progress",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_key", sa.String(80), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seconds", sa.Float, nullable=False),
        sa.Column("completed", sa.Boolean, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_key", "item_id", name="uq_vodloft_playback_user_item"))


def downgrade():
    op.drop_table("vodloft_playback_progress")
