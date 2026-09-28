"""Store Source publication time and Collection policy filters.

Revision ID: e30c9b81f4a2
Revises: d28b0e97c4a1
"""
from alembic import op
import sqlalchemy as sa

revision = "e30c9b81f4a2"
down_revision = "d28b0e97c4a1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_media_items") as batch:
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("vodloft_collection_download_profiles") as batch:
        batch.add_column(sa.Column("published_after", sa.Date, nullable=True))
        batch.add_column(sa.Column("published_before", sa.Date, nullable=True))
        batch.add_column(sa.Column("title_contains", sa.String(200), nullable=True))


def downgrade():
    with op.batch_alter_table("vodloft_collection_download_profiles") as batch:
        batch.drop_column("title_contains")
        batch.drop_column("published_before")
        batch.drop_column("published_after")
    with op.batch_alter_table("vodloft_media_items") as batch:
        batch.drop_column("published_at")
