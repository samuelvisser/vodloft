"""Collection automation, scan history and database-enforced active job identity.

Revision ID: e8c4d193a7f2
Revises: d4e6a1b9c203
"""
from alembic import op
import sqlalchemy as sa

revision = "e8c4d193a7f2"
down_revision = "d4e6a1b9c203"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("vodloft_collection_download_profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("collection_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("local_profile_ids", sa.JSON, nullable=False),
        sa.Column("backfill", sa.String(24), nullable=False),
        sa.Column("newest_count", sa.Integer, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("refresh_minutes", sa.Integer, nullable=False),
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("vodloft_collection_scans",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("collection_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String, nullable=False),
        sa.Column("runtime_version", sa.String, nullable=True),
        sa.Column("complete", sa.Boolean, nullable=False),
        sa.Column("entry_count", sa.Integer, nullable=False),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    with op.batch_alter_table("vodloft_acquisition_jobs") as batch:
        batch.add_column(sa.Column("active_key", sa.String, nullable=True))
        batch.create_unique_constraint("uq_vodloft_acquisition_jobs_active_key", ["active_key"])


def downgrade():
    with op.batch_alter_table("vodloft_acquisition_jobs") as batch:
        batch.drop_constraint("uq_vodloft_acquisition_jobs_active_key", type_="unique")
        batch.drop_column("active_key")
    op.drop_table("vodloft_collection_scans")
    op.drop_table("vodloft_collection_download_profiles")
