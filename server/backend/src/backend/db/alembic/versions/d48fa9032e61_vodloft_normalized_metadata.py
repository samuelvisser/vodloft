"""Common chapters, tracks, artwork and user classification.

Revision ID: d48fa9032e61
Revises: ca9d607e2b15
"""
from alembic import op
import sqlalchemy as sa

revision = "d48fa9032e61"
down_revision = "ca9d607e2b15"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_media_items") as batch:
        batch.add_column(sa.Column("normalized_metadata", sa.JSON, nullable=False, server_default="{}"))
        batch.add_column(sa.Column("user_kind", sa.String(32), nullable=True))
    with op.batch_alter_table("local_media_profiles_domain") as batch:
        batch.add_column(sa.Column("impairment", sa.String, nullable=True))


def downgrade():
    with op.batch_alter_table("local_media_profiles_domain") as batch:
        batch.drop_column("impairment")
    with op.batch_alter_table("vodloft_media_items") as batch:
        batch.drop_column("user_kind")
        batch.drop_column("normalized_metadata")
