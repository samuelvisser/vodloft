"""Persist independent demand, intentional suppression and retention policy.

Revision ID: b8c5a01e73d2
Revises: a642e07c8b51
"""
from alembic import op
import sqlalchemy as sa

revision = "b8c5a01e73d2"
down_revision = "a642e07c8b51"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_collection_download_profiles") as batch:
        batch.add_column(sa.Column("retain_newest", sa.Integer, nullable=True))
        batch.add_column(sa.Column("retain_days", sa.Integer, nullable=True))
    op.create_table("vodloft_media_demands",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_id", sa.Integer, sa.ForeignKey("local_media_profiles.id"), nullable=False),
        sa.Column("owner_kind", sa.String(24), nullable=False),
        sa.Column("owner_id", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_id", "profile_id", "owner_kind", "owner_id"))
    op.create_table("vodloft_media_suppressions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_id", sa.Integer, sa.ForeignKey("local_media_profiles.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_id", "profile_id"))
    # Existing local files predate explicit ownership. Preserve them as
    # intentional library holdings until an administrator removes them.
    op.execute("INSERT INTO vodloft_media_demands "
        "(item_id, profile_id, owner_kind, owner_id, created_at) "
        "SELECT DISTINCT item_id, profile_id, 'direct', item_id, CURRENT_TIMESTAMP "
        "FROM vodloft_artifacts WHERE profile_id IS NOT NULL")


def downgrade():
    op.drop_table("vodloft_media_suppressions")
    op.drop_table("vodloft_media_demands")
    with op.batch_alter_table("vodloft_collection_download_profiles") as batch:
        batch.drop_column("retain_days")
        batch.drop_column("retain_newest")
