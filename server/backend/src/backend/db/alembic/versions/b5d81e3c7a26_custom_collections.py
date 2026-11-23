"""Make every collection without a link of its own a custom collection.

Revision ID: b5d81e3c7a26
Revises: 7f3c2a9e5b14
Create Date: 2026-11-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "b5d81e3c7a26"
down_revision = "7f3c2a9e5b14"
branch_labels = None
depends_on = None

_KIND_COMMENT = (
    "What its own link is: channel, a creator's page of all their uploads, list, one list, or custom, no link: it gets "
    "all it holds from the lists the user gives it"
)
_OLD_KIND_COMMENT = "What its own link is: channel, a creator's page of all their uploads, or list, one list or no link"


def upgrade() -> None:
    collections = sa.table("collections", sa.column("kind"), sa.column("sharing_url"))
    op.execute(collections.update().where(collections.c.sharing_url.is_(None)).values(kind="custom"))
    with op.batch_alter_table("collections") as batch:
        batch.alter_column("kind", existing_type=sa.String(), existing_nullable=False, comment=_KIND_COMMENT,
                           existing_comment=_OLD_KIND_COMMENT)


def downgrade() -> None:
    collections = sa.table("collections", sa.column("kind"))
    op.execute(collections.update().where(collections.c.kind == "custom").values(kind="list"))
    with op.batch_alter_table("collections") as batch:
        batch.alter_column("kind", existing_type=sa.String(), existing_nullable=False, comment=_OLD_KIND_COMMENT,
                           existing_comment=_KIND_COMMENT)
