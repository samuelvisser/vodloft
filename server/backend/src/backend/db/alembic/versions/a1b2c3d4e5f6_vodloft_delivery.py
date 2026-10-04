"""Delivery targets, encrypted credentials and verified export identity.

Revision ID: a1b2c3d4e5f6
Revises: f73a4bc12590
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "f73a4bc12590"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("local_media_profiles_domain") as batch:
        batch.add_column(sa.Column("delivery_target_ids", sa.JSON, nullable=False, server_default="[]"))
    op.create_table("vodloft_media_server_targets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("base_url", sa.String, nullable=False),
        sa.Column("library_id", sa.String, nullable=False),
        sa.Column("local_prefix", sa.String, nullable=False),
        sa.Column("server_prefix", sa.String, nullable=False),
        sa.Column("secret_ciphertext", sa.String, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False))
    op.create_table("vodloft_media_server_exports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("placement_id", sa.Integer, sa.ForeignKey("vodloft_artifact_placements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", sa.Integer, sa.ForeignKey("vodloft_media_server_targets.id"), nullable=False),
        sa.Column("remote_id", sa.String, nullable=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("placement_id", "target_id"))


def downgrade():
    op.drop_table("vodloft_media_server_exports")
    op.drop_table("vodloft_media_server_targets")
    with op.batch_alter_table("local_media_profiles_domain") as batch:
        batch.drop_column("delivery_target_ids")
