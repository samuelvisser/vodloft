"""Retire profiles while preserving shared artifacts and execution history.

Revision ID: fba129de530c
Revises: e09c47fa281b
"""
from alembic import op
import sqlalchemy as sa

revision = "fba129de530c"
down_revision = "e09c47fa281b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("local_media_profiles_domain") as batch:
        batch.add_column(sa.Column("deleted", sa.Boolean, nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("local_media_profiles_domain") as batch:
        batch.drop_column("deleted")
