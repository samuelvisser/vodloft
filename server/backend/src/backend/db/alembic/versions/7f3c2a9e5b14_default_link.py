"""Give every collection without a link of its own one default link, such as the one its picture comes from.

Revision ID: 7f3c2a9e5b14
Revises: 0e8510a81f57
Create Date: 2026-11-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "7f3c2a9e5b14"
down_revision = "0e8510a81f57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The link the user chose for the collection's picture becomes its default link.
    with op.batch_alter_table("collection_lists") as batch:
        batch.alter_column(
            "picture", new_column_name="is_default", existing_type=sa.Boolean(), existing_nullable=False,
            existing_server_default=sa.false(),
            comment="The default link of a collection without a link of its own, such as the one its picture comes "
                    "from; such a collection has exactly one",
        )
    # A collection that has none yet starts with its first link.
    bind = op.get_bind()
    lists = sa.table(
        "collection_lists", sa.column("id"), sa.column("collection_id"), sa.column("site_position"),
        sa.column("is_default", sa.Boolean()),
    )
    collections = sa.table("collections", sa.column("id"), sa.column("sharing_url"))
    chosen = set(bind.execute(sa.select(lists.c.collection_id).where(lists.c.is_default.is_(True))).scalars())
    rows = bind.execute(
        sa.select(lists.c.id, lists.c.collection_id)
        .join(collections, collections.c.id == lists.c.collection_id)
        .where(collections.c.sharing_url.is_(None))
        .order_by(lists.c.collection_id, lists.c.site_position, lists.c.id)
    ).all()
    first: dict[int, int] = {}
    for list_id, collection_id in rows:
        if collection_id not in chosen:
            first.setdefault(collection_id, list_id)
    if first:
        bind.execute(lists.update().where(lists.c.id.in_(list(first.values()))).values(is_default=True))


def downgrade() -> None:
    with op.batch_alter_table("collection_lists") as batch:
        batch.alter_column(
            "is_default", new_column_name="picture", existing_type=sa.Boolean(), existing_nullable=False,
            existing_server_default=sa.false(),
            comment="Its picture is the collection's, for a collection without a link of its own; one at most per collection",
        )
