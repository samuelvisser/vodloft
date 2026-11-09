"""The Library lists the most recently opened Collections first unless a user picks another order.

The order was Often used before; users still on it move to Recently used.

Revision ID: 4a35f3a5b8ed
Revises: 9c4e1a7d2f60
Create Date: 2026-11-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "4a35f3a5b8ed"
down_revision = "9c4e1a7d2f60"
branch_labels = None
depends_on = None

_COMMENT = "How the user lists the Library's Collections: recently_used, often_used, name, release_date or added_at"
_OLD_COMMENT = "How the user lists the Library's Collections: often_used, recently_used, name, release_date or added_at"


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "library_collection_sort", existing_type=sa.String(), existing_nullable=False,
            server_default="recently_used", existing_server_default="often_used",
            comment=_COMMENT, existing_comment=_OLD_COMMENT,
        )
    op.execute(sa.text("UPDATE users SET library_collection_sort = 'recently_used' WHERE library_collection_sort = 'often_used'"))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "library_collection_sort", existing_type=sa.String(), existing_nullable=False,
            server_default="often_used", existing_server_default="recently_used",
            comment=_OLD_COMMENT, existing_comment=_COMMENT,
        )
