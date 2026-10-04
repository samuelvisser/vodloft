"""Invalidate transient leases when their private HLS descriptor shape changes.

Revision ID: e10ca894b7d3
Revises: d052a8e43bf1
"""
from alembic import op

revision = "e10ca894b7d3"
down_revision = "d052a8e43bf1"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DELETE FROM vodloft_playback_segments")
    op.execute("DELETE FROM vodloft_playback_sessions")


def downgrade():
    pass
