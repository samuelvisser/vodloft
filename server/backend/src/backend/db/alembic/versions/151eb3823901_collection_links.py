"""A collection is indexed from one or more links.

Every collection gets the link it was added with as its only link, and its episodes belong to that link.

Revision ID: 151eb3823901
Revises: 409629042e13
Create Date: 2026-11-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "151eb3823901"
down_revision = "409629042e13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collection_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "collection_id", sa.Integer(),
            sa.ForeignKey("collections.id", name="fk_collection_links_collection_id_collections", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(), nullable=False, comment="The link as the Source indexes it"),
        sa.Column("title", sa.String(), nullable=True, comment="The link's own title, the name of its season when it gets one"),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default="0",
            comment="Which link keeps a video several links list: the lowest",
        ),
        sa.Column(
            "placement", sa.String(), nullable=False, server_default="site_seasons",
            comment="Where the link's videos go: site_seasons, one_season or specials",
        ),
        sa.Column(
            "season_id", sa.Integer(),
            sa.ForeignKey("seasons.id", name="fk_collection_links_season_id_seasons", ondelete="SET NULL"),
            nullable=True, comment="The season of a one_season link, once it has one",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_collection_links"),
        sa.UniqueConstraint("collection_id", "url", name="uq_collection_link_url"),
    )
    op.create_index("ix_collection_links_collection_id", "collection_links", ["collection_id"])
    op.create_table(
        "collection_link_items",
        sa.Column(
            "link_id", sa.Integer(),
            sa.ForeignKey("collection_links.id", name="fk_collection_link_items_link_id_collection_links", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_slug", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("link_id", "source_slug", name="pk_collection_link_items"),
    )
    with op.batch_alter_table("media_items_episode") as batch:
        batch.add_column(sa.Column(
            "collection_link_id", sa.Integer(), nullable=True, comment="The link of the collection that keeps the episode",
        ))
        batch.create_foreign_key(
            "fk_media_items_episode_collection_link_id_collection_links", "collection_links",
            ["collection_link_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_media_items_episode_collection_link_id", ["collection_link_id"])

    op.execute(
        "INSERT INTO collection_links (collection_id, url, position, placement) "
        "SELECT id, sharing_url, 0, 'site_seasons' FROM collections"
    )
    op.execute(
        "UPDATE media_items_episode SET collection_link_id = ("
        "SELECT collection_links.id FROM collection_links "
        "WHERE collection_links.collection_id = media_items_episode.collection_id)"
    )
    op.execute(
        "INSERT INTO collection_link_items (link_id, source_slug) "
        "SELECT DISTINCT collection_link_id, source_slug FROM media_items_episode "
        "WHERE collection_link_id IS NOT NULL AND source_slug IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("media_items_episode") as batch:
        batch.drop_index("ix_media_items_episode_collection_link_id")
        batch.drop_constraint("fk_media_items_episode_collection_link_id_collection_links", type_="foreignkey")
        batch.drop_column("collection_link_id")
    op.drop_table("collection_link_items")
    op.drop_index("ix_collection_links_collection_id", table_name="collection_links")
    op.drop_table("collection_links")
