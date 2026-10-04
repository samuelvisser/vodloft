"""Crash-recoverable filesystem finalization journal.

Revision ID: d71e2b0a6c45
Revises: c9e72d1a40bf
"""
from alembic import op
import sqlalchemy as sa

revision = "d71e2b0a6c45"
down_revision = "c9e72d1a40bf"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("vodloft_file_finalizations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("vodloft_acquisition_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("destination", sa.String, nullable=False),
        sa.Column("placement_path", sa.String, nullable=True),
        sa.Column("previous_artifact_id", sa.Integer, sa.ForeignKey("vodloft_artifacts.id"), nullable=True),
        sa.Column("phase", sa.String(24), nullable=False),
        sa.UniqueConstraint("job_id"))


def downgrade():
    op.drop_table("vodloft_file_finalizations")
