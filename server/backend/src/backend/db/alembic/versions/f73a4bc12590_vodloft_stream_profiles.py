"""Collection Stream Profiles and scoped feed subscriptions.

Revision ID: f73a4bc12590
Revises: e8c4d193a7f2
"""
from alembic import op
import sqlalchemy as sa

revision = "f73a4bc12590"
down_revision = "e8c4d193a7f2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("vodloft_collection_stream_profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("collection_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("local_only", sa.Boolean, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False))
    with op.batch_alter_table("vodloft_feed_subscriptions") as batch:
        batch.drop_constraint("uq_vodloft_feed_subscriptions_collection_id", type_="unique")
        batch.add_column(sa.Column("stream_profile_id", sa.Integer, nullable=True))
        batch.create_foreign_key("fk_vodloft_feed_subscriptions_stream_profile_id",
                                 "vodloft_collection_stream_profiles", ["stream_profile_id"], ["id"])
        batch.create_unique_constraint("uq_vodloft_feed_subscriptions_stream_profile_id", ["stream_profile_id"])


def downgrade():
    with op.batch_alter_table("vodloft_feed_subscriptions") as batch:
        batch.drop_constraint("uq_vodloft_feed_subscriptions_stream_profile_id", type_="unique")
        batch.drop_constraint("fk_vodloft_feed_subscriptions_stream_profile_id", type_="foreignkey")
        batch.drop_column("stream_profile_id")
        batch.create_unique_constraint("uq_vodloft_feed_subscriptions_collection_id", ["collection_id"])
    op.drop_table("vodloft_collection_stream_profiles")
