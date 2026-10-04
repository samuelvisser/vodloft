"""Filter Collection feeds by publication date and title.

Revision ID: f04b2d781a63
Revises: e93a4f61b2d0
"""
from alembic import op
import sqlalchemy as sa

revision = "f04b2d781a63"
down_revision = "e93a4f61b2d0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_collection_stream_profiles") as batch:
        batch.add_column(sa.Column("published_after", sa.Date, nullable=True))
        batch.add_column(sa.Column("published_before", sa.Date, nullable=True))
        batch.add_column(sa.Column("title_contains", sa.String(200), nullable=True))


def downgrade():
    with op.batch_alter_table("vodloft_collection_stream_profiles") as batch:
        batch.drop_column("title_contains")
        batch.drop_column("published_before")
        batch.drop_column("published_after")
