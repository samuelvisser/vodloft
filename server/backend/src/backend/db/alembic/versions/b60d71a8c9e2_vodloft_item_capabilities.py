"""Store item-level Source capabilities separately from Media Type.

Revision ID: b60d71a8c9e2
Revises: a59c12d8e403
"""
from alembic import op
import sqlalchemy as sa

revision = "b60d71a8c9e2"
down_revision = "a59c12d8e403"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_media_items") as batch:
        batch.add_column(sa.Column("capabilities", sa.JSON, nullable=True))


def downgrade():
    with op.batch_alter_table("vodloft_media_items") as batch:
        batch.drop_column("capabilities")
