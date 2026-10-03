"""Local Media Profiles retain common representation intent.

Revision ID: d052a8e43bf1
Revises: ab27d01e8c64
"""
from alembic import op
import sqlalchemy as sa

revision = "d052a8e43bf1"
down_revision = "ab27d01e8c64"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("local_media_profiles_domain") as batch:
        batch.add_column(sa.Column("representation", sa.JSON, nullable=False, server_default="{}"))


def downgrade():
    with op.batch_alter_table("local_media_profiles_domain") as batch:
        batch.drop_column("representation")
