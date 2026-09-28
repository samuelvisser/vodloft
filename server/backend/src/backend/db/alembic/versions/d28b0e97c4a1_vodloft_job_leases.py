"""Lease durable acquisitions across worker and process restarts.

Revision ID: d28b0e97c4a1
Revises: c15e3a8d09bf
"""
from alembic import op
import sqlalchemy as sa

revision = "d28b0e97c4a1"
down_revision = "c15e3a8d09bf"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_acquisition_jobs") as batch:
        batch.add_column(sa.Column("lease_owner", sa.String(40), nullable=True))
        batch.add_column(sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("vodloft_acquisition_jobs") as batch:
        batch.drop_column("lease_until")
        batch.drop_column("lease_owner")
