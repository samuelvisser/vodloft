"""Persist encrypted Source leases and opaque HLS child references.

Revision ID: a642e07c8b51
Revises: f04b2d781a63
"""
from alembic import op
import sqlalchemy as sa

revision = "a642e07c8b51"
down_revision = "f04b2d781a63"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("vodloft_playback_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("reference_id", sa.Integer, sa.ForeignKey("vodloft_source_references.id"), nullable=True),
        sa.Column("transport", sa.String(16), nullable=False),
        sa.Column("lease_ciphertext", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("vodloft_playback_segments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("vodloft_playback_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("public_id", sa.String(40), nullable=False),
        sa.Column("url_ciphertext", sa.String, nullable=False),
        sa.UniqueConstraint("session_id", "public_id"))


def downgrade():
    op.drop_table("vodloft_playback_segments")
    op.drop_table("vodloft_playback_sessions")
