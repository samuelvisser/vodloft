"""Legacy media links and Collection/extra presentation metadata.

Revision ID: c9e72d1a40bf
Revises: b2d8e1c4a609
"""
from alembic import op
import sqlalchemy as sa

revision = "c9e72d1a40bf"
down_revision = "b2d8e1c4a609"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_media_items") as batch:
        batch.add_column(sa.Column("user_description", sa.String, nullable=True))
        batch.add_column(sa.Column("parent_id", sa.Integer, nullable=True))
        batch.add_column(sa.Column("extra_type", sa.String(32), nullable=True))
        batch.create_foreign_key("fk_vodloft_media_items_parent_id_vodloft_media_items",
            "vodloft_media_items", ["parent_id"], ["id"])
    with op.batch_alter_table("vodloft_collection_entries") as batch:
        batch.add_column(sa.Column("group", sa.String, nullable=True))
        batch.add_column(sa.Column("episode_number", sa.String, nullable=True))
        batch.add_column(sa.Column("role", sa.String(32), nullable=True))
    op.create_table("vodloft_legacy_media_links",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("legacy_type", sa.String(24), nullable=False),
        sa.Column("legacy_id", sa.Integer, nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("legacy_type", "legacy_id"))
    op.create_table("vodloft_movie_extra_parents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("movie_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("extra_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("extra_type", sa.String(32), nullable=False),
        sa.UniqueConstraint("movie_id", "extra_id"))


def downgrade():
    op.drop_table("vodloft_movie_extra_parents")
    op.drop_table("vodloft_legacy_media_links")
    with op.batch_alter_table("vodloft_collection_entries") as batch:
        batch.drop_column("role")
        batch.drop_column("episode_number")
        batch.drop_column("group")
    with op.batch_alter_table("vodloft_media_items") as batch:
        batch.drop_constraint("fk_vodloft_media_items_parent_id_vodloft_media_items", type_="foreignkey")
        batch.drop_column("extra_type")
        batch.drop_column("parent_id")
        batch.drop_column("user_description")
