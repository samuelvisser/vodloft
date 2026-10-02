"""Freeze verified Plex server identity and selected presentation mode.

Revision ID: f95c1a7e420d
Revises: f2d4c6b8901e
"""
from alembic import op
import sqlalchemy as sa

revision = "f95c1a7e420d"
down_revision = "f2d4c6b8901e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_media_server_exports") as batch:
        batch.add_column(sa.Column("remote_server_id", sa.String, nullable=True))
        batch.add_column(sa.Column("presentation_strategy", sa.String(32), nullable=True))


def downgrade():
    with op.batch_alter_table("vodloft_media_server_exports") as batch:
        batch.drop_column("presentation_strategy")
        batch.drop_column("remote_server_id")
