"""Let any of a creator's collections gather several of its feeds and lists

Besides the creator's own collection, any other collection of theirs that the user gives several feeds and lists of
one of the creator's accounts knows that account.

Revision ID: 4b9e1d7c2a60
Revises: fed6e334e01a
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "4b9e1d7c2a60"
down_revision = "fed6e334e01a"
branch_labels = None
depends_on = None


COMMENT = (
    "The creator's account whose feeds and lists it gathers as the user placed them, for a collection of the creator's "
    "other than the account's own collection"
)
FK = "fk_collections_creator_account_id"
INDEX = "ix_collections_creator_account_id"


def upgrade() -> None:
    column = sa.Column("creator_account_id", sa.Integer(), nullable=True, comment=COMMENT)
    if op.get_bind().dialect.name == "sqlite":
        # SQLite adds a foreign key only by rebuilding the table.
        with op.batch_alter_table("collections") as batch:
            batch.add_column(column)
            batch.create_index(INDEX, ["creator_account_id"])
            batch.create_foreign_key(FK, "creator_accounts", ["creator_account_id"], ["id"], ondelete="SET NULL")
        return
    op.add_column("collections", column)
    op.create_index(INDEX, "collections", ["creator_account_id"])
    op.create_foreign_key(FK, "collections", "creator_accounts", ["creator_account_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("collections") as batch:
            batch.drop_constraint(FK, type_="foreignkey")
            batch.drop_index(INDEX)
            batch.drop_column("creator_account_id")
        return
    op.drop_constraint(FK, "collections", type_="foreignkey")
    op.drop_index(INDEX, table_name="collections")
    op.drop_column("collections", "creator_account_id")
