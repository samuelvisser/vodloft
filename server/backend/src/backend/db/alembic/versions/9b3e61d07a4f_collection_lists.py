"""Lists and seasons are two things.

A link season becomes a list of its collection: a playlist or an album, which has a season. Several lists of a
collection can share one season. The data moves as it is: each link season is a list of its own season.

Revision ID: 9b3e61d07a4f
Revises: 841a4439c020
Create Date: 2026-11-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "9b3e61d07a4f"
down_revision = "841a4439c020"
branch_labels = None
depends_on = None

_LIST_COLUMNS = (
    "id, collection_id, ref, url, title, image_path, item_count, site_position, enabled, status, added_by_user, "
    "season_id, created_at"
)


def _lists_table(name: str, prefix: str, unique: str, season_comment: str) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "collection_id", sa.Integer(),
            sa.ForeignKey("collections.id", name=f"fk_{prefix}_collection_id_collections", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ref", sa.String(), nullable=False, comment="The Site's own id for the playlist"),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("image_path", sa.String(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column(
            "site_position", sa.Integer(), nullable=False, server_default="0", comment="Where the Site lists it, newest first",
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default="1",
            comment="Whether the playlist is a season, when only selected playlists are",
        ),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="known",
            comment="known, or new while it waits for the user's choice",
        ),
        sa.Column(
            "added_by_user", sa.Boolean(), nullable=False, server_default="0",
            comment="The user added the link, rather than it being one of the playlists of the collection's channel",
        ),
        sa.Column(
            "season_id", sa.Integer(),
            sa.ForeignKey("seasons.id", name=f"fk_{prefix}_season_id_seasons", ondelete="SET NULL"),
            nullable=True, comment=season_comment,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{prefix}"),
        sa.UniqueConstraint("collection_id", "ref", name=unique),
    )
    op.create_index(f"ix_{prefix}_collection_id", name, ["collection_id"])


def _items_table(name: str, column: str, lists: str) -> None:
    op.create_table(
        name,
        sa.Column(
            column, sa.Integer(),
            sa.ForeignKey(f"{lists}.id", name=f"fk_{name}_{column}_{lists}", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_slug", sa.String(), nullable=False),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default="0",
            comment="Where the playlist lists the video, from 0: its order at its Site",
        ),
        sa.PrimaryKeyConstraint(column, "source_slug", name=f"pk_{name}"),
    )


def _move(old_lists: str, old_items: str, old_column: str, new_lists: str, new_items: str, new_column: str) -> None:
    bind = op.get_bind()
    bind.execute(sa.text(f"INSERT INTO {new_lists} ({_LIST_COLUMNS}) SELECT {_LIST_COLUMNS} FROM {old_lists}"))
    bind.execute(sa.text(
        f"INSERT INTO {new_items} ({new_column}, source_slug, position) "
        f"SELECT {old_column}, source_slug, position FROM {old_items}"
    ))
    if bind.dialect.name == "postgresql":
        # The ids came along, so the sequence starts after them.
        bind.execute(sa.text(
            f"SELECT setval(pg_get_serial_sequence('{new_lists}', 'id'), COALESCE((SELECT MAX(id) FROM {new_lists}), 0) + 1, false)"
        ))
    op.drop_table(old_items)
    op.drop_index(f"ix_{old_lists}_collection_id", table_name=old_lists)
    op.drop_table(old_lists)


def upgrade() -> None:
    _lists_table(
        "collection_lists", "collection_lists", "uq_collection_list_ref",
        "The list's season, once it has one, which other lists of the collection may share",
    )
    _items_table("collection_list_items", "list_id", "collection_lists")
    _move("link_seasons", "link_season_items", "link_season_id", "collection_lists", "collection_list_items", "list_id")


def downgrade() -> None:
    _lists_table("link_seasons", "link_seasons", "uq_link_season_ref", "The playlist's season, once it has one")
    _items_table("link_season_items", "link_season_id", "link_seasons")
    # A season had one playlist: the others that shared it get one of their own when their collection is listed again.
    op.get_bind().execute(sa.text(
        "UPDATE collection_lists SET season_id = NULL WHERE id NOT IN "
        "(SELECT MIN(id) FROM collection_lists WHERE season_id IS NOT NULL GROUP BY season_id) AND season_id IS NOT NULL"
    ))
    _move("collection_lists", "collection_list_items", "list_id", "link_seasons", "link_season_items", "link_season_id")
