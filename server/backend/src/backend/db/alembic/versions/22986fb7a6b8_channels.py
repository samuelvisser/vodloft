"""Channels: a creator on one Site, and the sections their page offers.

Revision ID: 22986fb7a6b8
Revises: 151eb3823901
Create Date: 2026-11-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "22986fb7a6b8"
down_revision = "151eb3823901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False, comment="Id of the Source that looks the channel up"),
        sa.Column("site_key", sa.String(), sa.ForeignKey("sites.key", name="fk_channels_site_key_sites"), nullable=False),
        sa.Column("site_ref", sa.String(), nullable=False, comment="The Site's own id for the channel"),
        sa.Column(
            "url", sa.String(), nullable=True,
            comment="The channel's page; empty when the Site has none, such as a Daily Wire host",
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("handle", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("avatar_path", sa.String(), nullable=True),
        sa.Column("banner_path", sa.String(), nullable=True),
        sa.Column("links", sa.JSON(), nullable=False, server_default="[]", comment="The creator's own links"),
        sa.Column("facts", sa.JSON(), nullable=False, server_default="[]", comment='Short facts, such as "1.2M subscribers"'),
        sa.Column(
            "added_by_id", sa.Integer(),
            sa.ForeignKey("users.id", name="fk_channels_added_by_id_users", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_channels"),
        sa.UniqueConstraint("site_key", "site_ref", name="uq_channel_site_ref"),
    )
    op.create_index("ix_channels_uuid", "channels", ["uuid"], unique=True)
    op.create_index("ix_channels_slug", "channels", ["slug"], unique=True)
    op.create_index("ix_channels_site_key", "channels", ["site_key"])
    op.create_table(
        "channel_sections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "channel_id", sa.Integer(),
            sa.ForeignKey("channels.id", name="fk_channel_sections_channel_id_channels", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("ref", sa.String(), nullable=False, comment="The Site's own id for the section"),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, comment="feed, list or item"),
        sa.Column("role", sa.String(), nullable=False, server_default="main", comment="main, short or live"),
        sa.Column("kind_label", sa.String(), nullable=True, comment="What the Site calls it, such as Playlist"),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column("image_path", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("access", sa.String(), nullable=True, comment="The key of the access the section needs"),
        sa.Column("has_seasons", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("site_position", sa.Integer(), nullable=False, server_default="0", comment="Where the Site lists it"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_channel_sections"),
        sa.UniqueConstraint("channel_id", "ref", name="uq_channel_section_ref"),
    )
    op.create_index("ix_channel_sections_channel_id", "channel_sections", ["channel_id"])
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column("channel_id", sa.Integer(), nullable=True, comment="The channel it was added through"))
        batch.create_foreign_key(
            "fk_collections_channel_id_channels", "channels", ["channel_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_collections_channel_id", ["channel_id"])
    with op.batch_alter_table("collection_links") as batch:
        batch.add_column(sa.Column(
            "channel_section_id", sa.Integer(), nullable=True,
            comment="The channel section the link is; a section feeds one collection at most",
        ))
        batch.create_foreign_key(
            "fk_collection_links_channel_section_id_channel_sections", "channel_sections",
            ["channel_section_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_unique_constraint("uq_collection_links_channel_section_id", ["channel_section_id"])


def downgrade() -> None:
    with op.batch_alter_table("collection_links") as batch:
        batch.drop_constraint("uq_collection_links_channel_section_id", type_="unique")
        batch.drop_constraint("fk_collection_links_channel_section_id_channel_sections", type_="foreignkey")
        batch.drop_column("channel_section_id")
    with op.batch_alter_table("collections") as batch:
        batch.drop_index("ix_collections_channel_id")
        batch.drop_constraint("fk_collections_channel_id_channels", type_="foreignkey")
        batch.drop_column("channel_id")
    op.drop_table("channel_sections")
    op.drop_table("channels")
