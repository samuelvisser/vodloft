"""Record Source-scoped Collection scan checkpoints.

Revision ID: a92e7b14c6f0
Revises: e06f81c2d95a
"""
from alembic import op
import sqlalchemy as sa

revision = "a92e7b14c6f0"
down_revision = "e06f81c2d95a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_collection_scans") as batch:
        batch.add_column(sa.Column("connection_id", sa.Integer, nullable=True))
        batch.add_column(sa.Column("next_cursor", sa.String, nullable=True))
        batch.create_foreign_key("fk_vodloft_scan_connection", "vodloft_source_connections", ["connection_id"], ["id"])


def downgrade():
    with op.batch_alter_table("vodloft_collection_scans") as batch:
        batch.drop_constraint("fk_vodloft_scan_connection", type_="foreignkey")
        batch.drop_column("next_cursor")
        batch.drop_column("connection_id")
