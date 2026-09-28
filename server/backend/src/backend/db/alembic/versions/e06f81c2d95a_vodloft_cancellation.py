"""Durable cancellation request state.

Revision ID: e06f81c2d95a
Revises: d71e2b0a6c45
"""
from alembic import op
import sqlalchemy as sa

revision = "e06f81c2d95a"
down_revision = "d71e2b0a6c45"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_acquisition_jobs") as batch:
        batch.add_column(sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("vodloft_acquisition_jobs") as batch:
        batch.drop_column("cancel_requested")
