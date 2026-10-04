"""Persist Stream Profile live admission across Source status changes.

Revision ID: f2d4c6b8901e
Revises: e7c91a4d530b
"""
from alembic import op
import sqlalchemy as sa

revision = "f2d4c6b8901e"
down_revision = "e7c91a4d530b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_collection_stream_profiles") as batch:
        batch.add_column(sa.Column("include_live", sa.Boolean, nullable=False, server_default="0"))
    op.create_table("vodloft_live_admissions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stream_profile_id", sa.Integer, sa.ForeignKey(
            "vodloft_collection_stream_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey(
            "vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_reference_id", sa.Integer, sa.ForeignKey(
            "vodloft_source_references.id"), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("stream_profile_id", "item_id"))


def downgrade():
    op.drop_table("vodloft_live_admissions")
    with op.batch_alter_table("vodloft_collection_stream_profiles") as batch:
        batch.drop_column("include_live")
