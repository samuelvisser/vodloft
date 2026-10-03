"""Separate local accounts, request demand and per-user feed subscriptions.

Revision ID: ca9d607e2b15
Revises: e10ca894b7d3
"""
from alembic import op
import sqlalchemy as sa

revision = "ca9d607e2b15"
down_revision = "e10ca894b7d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("vodloft_users", sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False, unique=True),
        sa.Column("password_hash", sa.String, nullable=False), sa.Column("role", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False), sa.Column("can_subscribe", sa.Boolean, nullable=False),
        sa.Column("auto_approve", sa.Boolean, nullable=False), sa.Column("request_quota", sa.Integer, nullable=False),
        sa.Column("connection_ids", sa.JSON, nullable=False), sa.Column("target_ids", sa.JSON, nullable=False))
    op.create_table("vodloft_requests", sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_key", sa.String(80), nullable=False, index=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_id", sa.Integer, sa.ForeignKey("local_media_profiles.id"), nullable=False),
        sa.Column("reference_id", sa.Integer, sa.ForeignKey("vodloft_source_references.id"), nullable=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("vodloft_acquisition_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("state", sa.String(24), nullable=False), sa.Column("reason", sa.String, nullable=True),
        sa.Column("active_key", sa.String, unique=True, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    with op.batch_alter_table("vodloft_feed_subscriptions") as batch:
        batch.drop_constraint("uq_vodloft_feed_subscriptions_stream_profile_id", type_="unique")
        batch.add_column(sa.Column("user_key", sa.String(80), nullable=False, server_default="admin"))
        batch.create_unique_constraint("uq_vodloft_feed_profile_user", ["stream_profile_id", "user_key"])


def downgrade():
    with op.batch_alter_table("vodloft_feed_subscriptions") as batch:
        batch.drop_constraint("uq_vodloft_feed_profile_user", type_="unique")
        batch.drop_column("user_key")
        batch.create_unique_constraint("uq_vodloft_feed_subscriptions_stream_profile_id", ["stream_profile_id"])
    op.drop_table("vodloft_requests")
    op.drop_table("vodloft_users")
