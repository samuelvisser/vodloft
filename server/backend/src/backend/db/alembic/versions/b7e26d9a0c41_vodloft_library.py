"""Add normalized VodLoft library alongside the inherited WireLoft data.

Revision ID: b7e26d9a0c41
Revises: a9d73b8e5f21
"""
from alembic import op
import sqlalchemy as sa

revision = "b7e26d9a0c41"
down_revision = "a9d73b8e5f21"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("vodloft_domains",
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("hostname", sa.String, nullable=False),
        sa.Column("display_name", sa.String, nullable=False))
    op.create_index("ix_vodloft_domains_hostname", "vodloft_domains", ["hostname"], unique=True)
    op.create_table("vodloft_media_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("domain_id", sa.Integer, sa.ForeignKey("vodloft_domains.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False), sa.Column("title", sa.String, nullable=False),
        sa.Column("description", sa.String, nullable=True), sa.Column("duration", sa.Float, nullable=True),
        sa.Column("artwork_url", sa.String, nullable=True), sa.Column("user_title", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("vodloft_source_references",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", sa.Integer, sa.ForeignKey("vodloft_domains.id"), nullable=False),
        sa.Column("source_id", sa.String, nullable=False), sa.Column("namespace", sa.String, nullable=False),
        sa.Column("upstream_id", sa.String, nullable=False), sa.Column("url", sa.String, nullable=False),
        sa.UniqueConstraint("source_id", "domain_id", "namespace", "upstream_id"))
    op.create_table("vodloft_collection_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("collection_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False), sa.UniqueConstraint("collection_id", "item_id"))
    op.create_table("vodloft_artifacts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.String, nullable=False), sa.Column("size", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_id"), sa.UniqueConstraint("path"))
    op.create_table("vodloft_acquisition_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("vodloft_media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reference_id", sa.Integer, sa.ForeignKey("vodloft_source_references.id"), nullable=False),
        sa.Column("state", sa.String(32), nullable=False), sa.Column("error", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for table in ("vodloft_acquisition_jobs", "vodloft_artifacts", "vodloft_collection_entries",
                  "vodloft_source_references", "vodloft_media_items", "vodloft_domains"):
        op.drop_table(table)
