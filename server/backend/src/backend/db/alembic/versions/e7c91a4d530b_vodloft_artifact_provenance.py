"""Identify compatible artifacts by their frozen Source and representation.

Revision ID: e7c91a4d530b
Revises: d9e3a4b1c750
"""
from alembic import op
import sqlalchemy as sa

revision = "e7c91a4d530b"
down_revision = "d9e3a4b1c750"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_artifacts") as batch:
        batch.add_column(sa.Column("source_reference_id", sa.Integer,
            sa.ForeignKey("vodloft_source_references.id"), nullable=True))
        batch.add_column(sa.Column("representation_key", sa.String(64), nullable=True))
        batch.create_index("ix_vodloft_artifacts_representation_key", ["representation_key"])


def downgrade():
    with op.batch_alter_table("vodloft_artifacts") as batch:
        batch.drop_index("ix_vodloft_artifacts_representation_key")
        batch.drop_column("representation_key")
        batch.drop_column("source_reference_id")
