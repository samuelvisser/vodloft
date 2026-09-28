"""Allow separate account references for one Source media identity.

Revision ID: b2d8e1c4a609
Revises: a1b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa

revision = "b2d8e1c4a609"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_source_references") as batch:
        batch.drop_constraint("uq_vodloft_source_references_source_id", type_="unique")
        batch.add_column(sa.Column("connection_key", sa.Integer, nullable=False, server_default="0"))
        batch.create_unique_constraint("uq_vodloft_source_references_source_id",
            ["source_id", "domain_id", "namespace", "upstream_id", "connection_key"])


def downgrade():
    with op.batch_alter_table("vodloft_source_references") as batch:
        batch.drop_constraint("uq_vodloft_source_references_source_id", type_="unique")
        batch.drop_column("connection_key")
        batch.create_unique_constraint("uq_vodloft_source_references_source_id",
            ["source_id", "domain_id", "namespace", "upstream_id"])
