"""Persist stable VodLoft subscription and enclosure identities.

Revision ID: c1a8f42d6e90
Revises: b7e26d9a0c41
"""
from alembic import op
import sqlalchemy as sa

revision = "c1a8f42d6e90"
down_revision = "b7e26d9a0c41"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("vodloft_feed_subscriptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("collection_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.UniqueConstraint("collection_id"), sa.UniqueConstraint("token"))
    op.create_table("vodloft_published_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subscription_id", sa.Integer, sa.ForeignKey("vodloft_feed_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.String, nullable=False), sa.Column("size", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("subscription_id", "item_id"), sa.UniqueConstraint("path"))


def downgrade():
    op.drop_table("vodloft_published_entries")
    op.drop_table("vodloft_feed_subscriptions")
