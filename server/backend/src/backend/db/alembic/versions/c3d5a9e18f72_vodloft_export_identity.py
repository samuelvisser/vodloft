"""Freeze media-server presentation numbering and external episode mapping.

Revision ID: c3d5a9e18f72
Revises: b8c5a01e73d2
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d5a9e18f72"
down_revision = "b8c5a01e73d2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_media_server_exports") as batch:
        batch.add_column(sa.Column("remote_episode_id", sa.String, nullable=True))
        batch.add_column(sa.Column("season_number", sa.Integer, nullable=True))
        batch.add_column(sa.Column("episode_number", sa.Integer, nullable=True))


def downgrade():
    with op.batch_alter_table("vodloft_media_server_exports") as batch:
        batch.drop_column("episode_number")
        batch.drop_column("season_number")
        batch.drop_column("remote_episode_id")
