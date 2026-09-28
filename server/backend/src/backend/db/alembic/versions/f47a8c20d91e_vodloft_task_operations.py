"""Correlate durable acquisitions with WireLoft TaskOperations.

Revision ID: f47a8c20d91e
Revises: e30c9b81f4a2
"""
from alembic import op
import sqlalchemy as sa

revision = "f47a8c20d91e"
down_revision = "e30c9b81f4a2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_acquisition_jobs") as batch:
        batch.add_column(sa.Column("operation_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_vodloft_job_operation", "task_operations", ["operation_id"], ["id"])


def downgrade():
    with op.batch_alter_table("vodloft_acquisition_jobs") as batch:
        batch.drop_constraint("fk_vodloft_job_operation", type_="foreignkey")
        batch.drop_column("operation_id")
