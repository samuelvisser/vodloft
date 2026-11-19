"""Movies can belong to a creator

A movie keeps the creator it belongs to, such as a Daily Wire host's movie. Movies already in the library that a
creator's account lists join that creator.

Revision ID: bd6c56bd1a8d
Revises: 8bf741c29247
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "bd6c56bd1a8d"
down_revision = "8bf741c29247"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_items_movie") as batch:
        batch.add_column(sa.Column("creator_id", sa.Integer(), nullable=True, comment="The creator the movie belongs to"))
        batch.create_foreign_key(
            "fk_media_items_movie_creator_id_creators", "creators", ["creator_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_media_items_movie_creator_id", ["creator_id"])
    # A movie a creator's account lists, as a single item, belongs to that creator.
    op.get_bind().execute(sa.text(
        "UPDATE media_items_movie SET creator_id = ("
        " SELECT creator_accounts.creator_id FROM creator_sections"
        " JOIN creator_accounts ON creator_accounts.id = creator_sections.account_id"
        " JOIN media_items ON media_items.id = media_items_movie.id"
        " WHERE creator_sections.kind = 'item' AND creator_sections.ref = media_items_movie.slug"
        " AND creator_accounts.source_key = media_items.source_key"
        " ORDER BY creator_accounts.id LIMIT 1)"
    ))


def downgrade() -> None:
    with op.batch_alter_table("media_items_movie") as batch:
        batch.drop_index("ix_media_items_movie_creator_id")
        batch.drop_constraint("fk_media_items_movie_creator_id_creators", type_="foreignkey")
        batch.drop_column("creator_id")
