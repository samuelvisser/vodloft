"""Persist live state and normalized format choices without provider fields.

Revision ID: d9e3a4b1c750
Revises: c3d5a9e18f72
"""
from alembic import op
import sqlalchemy as sa

revision = "d9e3a4b1c750"
down_revision = "c3d5a9e18f72"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_media_items") as batch:
        batch.add_column(sa.Column("is_live", sa.Boolean, nullable=True))
        batch.add_column(sa.Column("formats", sa.JSON, nullable=True))


def downgrade():
    with op.batch_alter_table("vodloft_media_items") as batch:
        batch.drop_column("formats")
        batch.drop_column("is_live")
