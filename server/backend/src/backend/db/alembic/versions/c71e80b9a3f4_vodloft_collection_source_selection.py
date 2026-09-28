"""Bind Collection automation to an explicitly selected Source account.

Revision ID: c71e80b9a3f4
Revises: b60d71a8c9e2
"""
from alembic import op
import sqlalchemy as sa

revision = "c71e80b9a3f4"
down_revision = "b60d71a8c9e2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_collection_download_profiles") as batch:
        batch.add_column(sa.Column("source_reference_id", sa.Integer, nullable=True))
        batch.create_foreign_key("fk_vodloft_policy_source_reference",
            "vodloft_source_references", ["source_reference_id"], ["id"])


def downgrade():
    with op.batch_alter_table("vodloft_collection_download_profiles") as batch:
        batch.drop_constraint("fk_vodloft_policy_source_reference", type_="foreignkey")
        batch.drop_column("source_reference_id")
