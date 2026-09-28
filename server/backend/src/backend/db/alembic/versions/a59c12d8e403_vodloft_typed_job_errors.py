"""Persist normalized acquisition failure reason and stage.

Revision ID: a59c12d8e403
Revises: f47a8c20d91e
"""
from alembic import op
import sqlalchemy as sa

revision = "a59c12d8e403"
down_revision = "f47a8c20d91e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_acquisition_jobs") as batch:
        batch.add_column(sa.Column("error_code", sa.String(32), nullable=True))
        batch.add_column(sa.Column("failed_stage", sa.String(32), nullable=True))


def downgrade():
    with op.batch_alter_table("vodloft_acquisition_jobs") as batch:
        batch.drop_column("failed_stage")
        batch.drop_column("error_code")
