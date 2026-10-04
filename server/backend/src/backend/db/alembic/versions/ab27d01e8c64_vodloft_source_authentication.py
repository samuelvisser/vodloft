"""Persist scoped Source authentication without storing plaintext credentials.

Revision ID: ab27d01e8c64
Revises: f95c1a7e420d
"""
from alembic import op
import sqlalchemy as sa

revision = "ab27d01e8c64"
down_revision = "f95c1a7e420d"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_source_connections") as batch:
        batch.add_column(sa.Column("authentication_reference", sa.String(64), nullable=True))


def downgrade():
    with op.batch_alter_table("vodloft_source_connections") as batch:
        batch.drop_column("authentication_reference")
